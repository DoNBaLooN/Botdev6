"""Handlers for the roulette module."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import hmac
import io
import random
import secrets
import time
from contextlib import asynccontextmanager
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Iterable
from uuid import UUID, uuid4

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hooks.hooks import register_hook
from handlers.notifications.notify_utils import send_messages_with_limit
from logger import logger
from filters.admin import IsAdminFilter

from . import settings, texts
from .db import (
    BonusDAO,
    JackpotDAO,
    LeaderboardDAO,
    RouletteUserDAO,
    SpinRecord,
    count_winning_days,
    get_active_users,
    get_daily_totals,
    get_notify_enabled,
    get_user_balance,
    load_last_spins,
    record_spin,
    set_notify_enabled,
    touch_last_spin,
)
from .models import RouletteJackpot, RoulettePreference, RouletteSpin, RouletteUser
from .wallet import InsufficientFunds, WalletReservation, WalletService
from .state import state as module_state

router = Router(name="ruletka")

MENU_CALLBACK = "ruletka:menu"
SPIN_CALLBACK = "ruletka:spin"
PRIZES_CALLBACK = "ruletka:prizes"
STATS_CALLBACK = "ruletka:stats"
LEADERBOARD_CALLBACK = "ruletka:leaderboard"
LEADERBOARD_REFRESH_CALLBACK = "ruletka:leaderboard:refresh"
BONUS_CALLBACK = "ruletka:bonus"
BACK_CALLBACK = "profile"
NOTIFY_TOGGLE_CALLBACK = "ruletka:notify_toggle"
ADMIN_CALLBACK_PREFIX = "ruletka:admin"
ADMIN_PANEL_BACK = "admin_panel:admin:1"


class RouletteAdminCallback(CallbackData, prefix="ruletka_admin"):
    action: str


class RouletteAdminStates(StatesGroup):
    waiting_tg_id = State()
    waiting_base_jackpot = State()


@dataclass(slots=True)
class _JackpotCache:
    amount: Decimal
    expires_at: float


class _NotificationQuota:
    def __init__(self) -> None:
        self._storage: dict[tuple[int, str], tuple[date, int]] = {}

    def allow(self, tg_id: int, channel: str, limit: int) -> bool:
        if limit <= 0:
            return True
        today = date.today()
        key = (tg_id, channel)
        stored_date, count = self._storage.get(key, (today, 0))
        if stored_date != today:
            self._storage[key] = (today, 0)
            stored_date, count = today, 0
        if count >= limit:
            return False
        self._storage[key] = (stored_date, count + 1)
        return True


@dataclass(slots=True)
class PrizeConfig:
    code: str
    title: str
    amount: Decimal | str
    weight: int


@dataclass(slots=True)
class RarityConfig:
    name: str
    weight: float  # поддерживаем дробные проценты
    prizes: list[PrizeConfig]


_USER_LOCKS: dict[int, asyncio.Lock] = {}
_LAST_SPIN_AT: dict[int, float] = {}
_JACKPOT_CACHE: _JackpotCache | None = None
_NOTIFICATION_QUOTA = _NotificationQuota()
_LEADERBOARD_SCOPES = {"today", "all_time"}


@asynccontextmanager
async def _transaction(session: AsyncSession):
    """Ensure the session has a clean transaction and commit on success."""

    if session.in_transaction():
        try:
            yield
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()
    else:
        async with session.begin():
            yield


def insert_hook_buttons(*items: Any) -> list[dict[str, Any]]:
    """Normalize hook button operations and guard against malformed payloads."""

    ops: list[dict[str, Any]] = []
    for item in items:
        if not item:
            continue
        if isinstance(item, (list, tuple)):
            ops.extend(insert_hook_buttons(*item))
            continue
        if not isinstance(item, dict):
            logger.warning("[Ruletka] Invalid hook payload type: %s", type(item))
            continue
        if "after" in item and "button" not in item:
            logger.warning("[Ruletka] Hook payload missing button for 'after': %s", item)
            continue
        if any(key in item for key in ("button", "remove", "remove_prefix")):
            ops.append(item)
        else:
            logger.warning("[Ruletka] Unsupported hook payload keys: %s", item)
    return ops


def _module_enabled() -> bool:
    return settings.ENABLED and module_state.enabled


def _extract_bundle_names(bundles: Iterable[Any] | None) -> list[str]:
    names: list[str] = []
    if not bundles:
        return names
    for item in bundles:
        if isinstance(item, dict):
            title = item.get("title") or item.get("name") or item.get("label")
            if title:
                names.append(str(title).lower())
        else:
            names.append(str(item).lower())
    return names


def _format_amount(value: Decimal | float | int | str | None) -> str:
    if value is None:
        return "0"
    if isinstance(value, Decimal):
        dec = value
    else:
        dec = Decimal(str(value))
    dec = dec.quantize(Decimal("0.01"))
    text = format(dec, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _get_lock(tg_id: int) -> asyncio.Lock:
    lock = _USER_LOCKS.get(tg_id)
    if lock is None:
        lock = asyncio.Lock()
        _USER_LOCKS[tg_id] = lock
    return lock


def _build_rarities() -> tuple[list[RarityConfig], dict[str, int], dict[str, PrizeConfig]]:
    configs: list[RarityConfig] = []
    index: dict[str, int] = {}
    prize_index: dict[str, PrizeConfig] = {}
    total_weight = Decimal("0")
    for order, rarity in enumerate(settings.RARITIES):
        name = str(rarity.get("name"))
        weight_value = Decimal(str(rarity.get("weight", 0)))
        if weight_value <= 0:
            raise ValueError(f"Rarity '{name}' must have positive weight")
        weight = float(weight_value)  # не теряем доли процента
        total_weight += weight_value
        prizes: list[PrizeConfig] = []
        for prize in rarity.get("prizes", []):
            amount = prize.get("amount")
            if isinstance(amount, str):
                if amount.upper() != "JACKPOT":
                    amount = Decimal(str(amount))
            else:
                amount = Decimal(str(amount))
            prize_config = PrizeConfig(
                code=str(prize.get("code")),
                title=str(prize.get("title")),
                amount=amount,
                weight=int(prize.get("weight", 1)),
            )
            if prize_config.weight <= 0:
                raise ValueError(f"Prize '{prize_config.code}' must have positive weight")
            prizes.append(prize_config)
            prize_index[prize_config.code] = prize_config
        if not prizes:
            raise ValueError(f"Rarity '{name}' must contain prizes")
        configs.append(RarityConfig(name=name, weight=weight, prizes=prizes))
        index[name] = order
    if (total_weight - Decimal("100")).copy_abs() > Decimal("0.5"):
        raise ValueError("RARITIES weights must sum to 100 ±0.5")
    return configs, index, prize_index


RARITIES, RARITY_INDEX, PRIZE_INDEX = _build_rarities()


async def _get_cached_jackpot(session: AsyncSession) -> Decimal:
    global _JACKPOT_CACHE
    now = time.monotonic()
    if _JACKPOT_CACHE and _JACKPOT_CACHE.expires_at > now:
        return _JACKPOT_CACHE.amount
    dao = JackpotDAO(session)
    amount = await dao.get_amount()
    _JACKPOT_CACHE = _JackpotCache(
        amount=amount,
        expires_at=now + max(1, settings.JACKPOT_CACHE_TTL_S),
    )
    return amount


def _set_jackpot_cache(amount: Decimal) -> None:
    global _JACKPOT_CACHE
    _JACKPOT_CACHE = _JackpotCache(
        amount=Decimal(amount),
        expires_at=time.monotonic() + max(1, settings.JACKPOT_CACHE_TTL_S),
    )


def _pick_rarity(
    rng: random.Random,
    *,
    min_rarity: str | None = None,
) -> tuple[RarityConfig, float]:
    configs = RARITIES
    if min_rarity and min_rarity in RARITY_INDEX:
        min_index = RARITY_INDEX[min_rarity]
        configs = RARITIES[: min_index + 1]
    total = sum(float(item.weight) for item in configs)
    roll = rng.uniform(0, total)
    cumulative = 0.0
    for rarity in configs:
        cumulative += float(rarity.weight)
        if roll <= cumulative:
            return rarity, roll
    return configs[-1], roll


def _pick_prize(rarity: RarityConfig, rng: random.Random) -> tuple[PrizeConfig, float]:
    total = sum(prize.weight for prize in rarity.prizes)
    roll = rng.uniform(0, total)
    cumulative = 0.0
    for prize in rarity.prizes:
        cumulative += prize.weight
        if roll <= cumulative:
            return prize, roll
    return rarity.prizes[-1], roll


def _build_seed(tg_id: int) -> tuple[str, random.Random]:
    timestamp_ms = int(time.time() * 1000)
    nonce = secrets.token_hex(8)
    payload = f"{tg_id}:{timestamp_ms}:{nonce}".encode()
    digest = hmac.new(settings.SEED_SECRET.encode(), payload, hashlib.sha256).hexdigest()
    rng = random.Random(int(digest, 16))
    return digest, rng


def _build_animation(rng: random.Random, final_icons: tuple[str, str, str]) -> tuple[list[tuple[str, str, str]], list[float]]:
    steps = rng.randint(settings.ANIMATION_MIN_STEPS, settings.ANIMATION_MAX_STEPS)
    steps = max(settings.ANIMATION_MIN_STEPS, min(steps, settings.ANIMATION_MAX_STEPS, 10))
    frames: list[tuple[str, str, str]] = []
    icons = list(settings.WHEEL_ICONS)
    for _ in range(steps - 1):
        frame = tuple(rng.choice(icons) for _ in range(3))
        attempts = 0
        while frame == final_icons and attempts < 5:
            frame = tuple(rng.choice(icons) for _ in range(3))
            attempts += 1
        if frame == final_icons:
            frame = tuple(rng.choice(icons) for _ in range(3))
        frames.append(frame)
    frames.append(final_icons)

    min_delay, max_delay = settings.ANIMATION_DELAY_MS
    delays = [rng.randint(min_delay, max_delay) / 1000 for _ in range(len(frames))]
    if len(delays) >= 2:
        delays[-2] *= 1.5
        delays[-1] *= 2
    return frames, delays


def _resolve_final_icons(rng: random.Random, prize_code: str | None) -> tuple[str, str, str]:
    code = (prize_code or "").upper()
    icon = settings.PRIZE_ICONS.get(code)
    if icon:
        return (icon, icon, icon)
    return tuple(rng.choice(settings.WHEEL_ICONS) for _ in range(3))


def _resolve_prize_title(prize_code: str | None, fallback: str = "—") -> str:
    if not prize_code:
        return fallback
    prize = PRIZE_INDEX.get(prize_code)
    if prize:
        return prize.title
    return prize_code


def _main_keyboard(
    free_spins: int,
    bet: Decimal,
    *,
    notify_enabled: bool | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    spin_label = texts.BUTTON_SPIN.format(
        amount=_format_amount(bet),
        currency=settings.CURRENCY_EMOJI,
    )
    if free_spins > 0:
        spin_label = texts.BUTTON_SPIN_FREE.format(
            amount=_format_amount(bet),
            currency=settings.CURRENCY_EMOJI,
            free_spins=free_spins,
        )
    builder.row(InlineKeyboardButton(text=spin_label, callback_data=SPIN_CALLBACK))
    builder.row(
        InlineKeyboardButton(text=texts.BUTTON_STATS, callback_data=STATS_CALLBACK),
        InlineKeyboardButton(text=texts.BUTTON_PRIZES, callback_data=PRIZES_CALLBACK),
    )
    builder.row(
        InlineKeyboardButton(
            text=texts.BUTTON_LEADERBOARD,
            callback_data=_build_leaderboard_callback(LEADERBOARD_CALLBACK),
        ),
        InlineKeyboardButton(text=texts.BUTTON_BONUS, callback_data=BONUS_CALLBACK),
    )
    if (
        notify_enabled is not None
        and settings.ALLOW_USER_NOTIFY_TOGGLE
        and settings.NOTIFICATIONS_ENABLED
    ):
        toggle_text = (
            texts.BUTTON_NOTIFY_DISABLE if notify_enabled else texts.BUTTON_NOTIFY_ENABLE
        )
        builder.row(InlineKeyboardButton(text=toggle_text, callback_data=NOTIFY_TOGGLE_CALLBACK))
    builder.row(InlineKeyboardButton(text=texts.BUTTON_BACK, callback_data=BACK_CALLBACK))
    return builder.as_markup()


def _insufficient_funds_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=texts.BUTTON_BALANCE, callback_data="balance"))
    builder.row(InlineKeyboardButton(text=texts.BUTTON_BACK, callback_data=BACK_CALLBACK))
    return builder.as_markup()


async def _show_insufficient_funds(callback: CallbackQuery) -> None:
    message = callback.message
    markup = _insufficient_funds_keyboard()
    if message is None:
        await callback.bot.send_message(
            callback.from_user.id,
            texts.INSUFFICIENT_FUNDS_PROMPT,
            reply_markup=markup,
        )
        return
    try:
        await message.edit_text(texts.INSUFFICIENT_FUNDS_PROMPT, reply_markup=markup)
    except TelegramBadRequest:
        await callback.bot.send_message(
            callback.from_user.id,
            texts.INSUFFICIENT_FUNDS_PROMPT,
            reply_markup=markup,
        )


async def _render_menu(source: CallbackQuery | Message, session: AsyncSession) -> None:
    user_id = source.from_user.id
    if not _module_enabled():
        disabled_text = texts.MODULE_DISABLED
        if isinstance(source, CallbackQuery) and source.message:
            await source.message.edit_text(disabled_text)
        else:
            await source.answer(disabled_text)
        return

    user = await RouletteUserDAO(session).get_or_create(user_id)
    jackpot = await _get_cached_jackpot(session)
    free_spins = int(user.free_spins or 0)
    threshold = settings.GUARANTEE_VIP if user.vip_active else settings.GUARANTEE_BASE
    guarantee_left = max(0, threshold - int(user.guarantee_counter or 0))
    notify_pref: bool | None = None
    if settings.ALLOW_USER_NOTIFY_TOGGLE and settings.NOTIFICATIONS_ENABLED:
        notify_pref = await get_notify_enabled(session, user_id)
    description = texts.render_menu_description(
        jackpot=_format_amount(jackpot),
        bet=_format_amount(settings.BET_AMOUNT),
        free_spins=free_spins,
        vip_active=user.vip_active,
        guarantee_left=guarantee_left,
        guarantee_threshold=threshold,
        guarantee_min=settings.GUARANTEE_MIN_RARITY,
        currency=settings.CURRENCY_EMOJI,
    )
    text = f"{texts.TITLE_MENU}\n\n{description}"
    markup = _main_keyboard(
        free_spins,
        settings.BET_AMOUNT,
        notify_enabled=notify_pref,
    )
    if isinstance(source, CallbackQuery):
        target = source.message
        if target:
            try:
                await target.edit_text(text, reply_markup=markup)
            except TelegramBadRequest:
                await target.answer(text, reply_markup=markup)
    else:
        await source.answer(text, reply_markup=markup)


def _mask_tg_id(tg_id: int) -> str:
    text = str(tg_id)
    if len(text) <= 4:
        return text
    prefix_len = max(1, len(text) - 4)
    return f"{text[:prefix_len]}{'*' * 4}"


def _normalize_leaderboard_scope(scope: str | None) -> str:
    if scope in _LEADERBOARD_SCOPES:
        return scope
    if settings.LEADERBOARD_SCOPE in _LEADERBOARD_SCOPES:
        return settings.LEADERBOARD_SCOPE
    return "all_time"


def _extract_scope_from_payload(payload: str | None) -> str | None:
    if not payload or "?" not in payload:
        return None
    query = payload.split("?", 1)[1]
    for part in query.split("&"):
        key, _, value = part.partition("=")
        if key == "scope":
            return value
    return None


def _build_leaderboard_callback(base: str, scope: str | None = None) -> str:
    resolved_scope = _normalize_leaderboard_scope(scope)
    return f"{base}?scope={resolved_scope}"


async def _show_leaderboard(
    callback: CallbackQuery,
    session: AsyncSession,
    *,
    scope: str | None = None,
) -> None:
    today = date.today()
    dao = LeaderboardDAO(session)
    resolved_scope = _normalize_leaderboard_scope(scope)
    if resolved_scope == "today":
        top = await dao.fetch_top(day=today, limit=settings.LEADERBOARD_TOP_N)
        position, total = await dao.get_user_position(tg_id=callback.from_user.id, day=today)
    else:
        top = await dao.fetch_top_all_time(limit=settings.LEADERBOARD_TOP_N)
        position, total = await dao.get_user_position_all_time(tg_id=callback.from_user.id)
    body = []
    for idx, (tg_id, amount) in enumerate(top, start=1):
        body.append(
            texts.LEADERBOARD_ROW.format(
                place=idx,
                mask=_mask_tg_id(tg_id),
                amount=_format_amount(amount),
                currency=settings.CURRENCY_EMOJI,
            )
        )
    if not body:
        body.append(texts.LEADERBOARD_EMPTY)
    summary = "".join(body)
    if position is not None:
        summary += texts.LEADERBOARD_YOUR_PLACE.format(
            place=position,
            amount=_format_amount(total),
            currency=settings.CURRENCY_EMOJI,
        )
    header = texts.leaderboard_title(resolved_scope, limit=settings.LEADERBOARD_TOP_N)
    text = f"{header}\n{summary}"
    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        InlineKeyboardButton(
            text=texts.leaderboard_scope_button("today", active=resolved_scope == "today"),
            callback_data=_build_leaderboard_callback(LEADERBOARD_CALLBACK, "today"),
        ),
        InlineKeyboardButton(
            text=texts.leaderboard_scope_button("all_time", active=resolved_scope == "all_time"),
            callback_data=_build_leaderboard_callback(LEADERBOARD_CALLBACK, "all_time"),
        ),
    )
    keyboard.row(
        InlineKeyboardButton(
            text=texts.BUTTON_LEADERBOARD_REFRESH,
            callback_data=_build_leaderboard_callback(LEADERBOARD_REFRESH_CALLBACK, resolved_scope),
        )
    )
    keyboard.row(InlineKeyboardButton(text=texts.BUTTON_MAIN_MENU, callback_data=MENU_CALLBACK))
    try:
        await callback.message.edit_text(text, reply_markup=keyboard.as_markup())
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=keyboard.as_markup())


async def _show_stats(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await RouletteUserDAO(session).get_or_create(callback.from_user.id)
    threshold = settings.GUARANTEE_VIP if user.vip_active else settings.GUARANTEE_BASE
    guarantee_left = max(0, threshold - int(user.guarantee_counter or 0))
    spins_total = int(user.spins_total or 0)
    wins_total = int(user.wins_total or 0)
    sum_win = Decimal(user.sum_win or 0)
    avg_win = sum_win / wins_total if wins_total else Decimal("0")
    winrate = Decimal("0")
    if spins_total:
        winrate = (Decimal(wins_total) / Decimal(spins_total)) * Decimal("100")
    winning_days = await count_winning_days(session, tg_id=user.tg_id)
    guarantee_min_label = settings.GUARANTEE_MIN_RARITY
    rarity_emoji = settings.RARITY_EMOJI.get(guarantee_min_label)
    if rarity_emoji:
        guarantee_min_label = f"{rarity_emoji} {guarantee_min_label}"
    text = texts.STATS_HEADER + texts.STATS_TEMPLATE.format(
        spins_total=spins_total,
        wins_total=wins_total,
        winrate=_format_amount(winrate),
        sum_win=_format_amount(sum_win),
        avg_win=_format_amount(avg_win),
        best_win=_format_amount(Decimal(user.best_win or 0)),
        last_jackpot=_format_amount(Decimal(user.last_jackpot_win or 0)),
        streak_now=user.streak_now,
        streak_best=user.streak_best,
        winning_days=winning_days,
        guarantee_left=guarantee_left,
        guarantee_min=guarantee_min_label,
        vip="Да" if user.vip_active else "Нет",
        currency=settings.CURRENCY_EMOJI,
    )
    keyboard = InlineKeyboardBuilder()
    keyboard.row(InlineKeyboardButton(text=texts.BUTTON_MAIN_MENU, callback_data=MENU_CALLBACK))
    await callback.message.edit_text(text, reply_markup=keyboard.as_markup())


async def _show_prizes(callback: CallbackQuery) -> None:
    keyboard = InlineKeyboardBuilder()
    keyboard.row(InlineKeyboardButton(text=texts.BUTTON_MAIN_MENU, callback_data=MENU_CALLBACK))
    await callback.message.edit_text(texts.format_rarity_prizes(), reply_markup=keyboard.as_markup())


async def _claim_bonus(callback: CallbackQuery, session: AsyncSession) -> None:
    if not settings.BONUS_ENABLED:
        await callback.answer(texts.BONUS_DISABLED, show_alert=True)
        return
    now = datetime.utcnow()
    user_id = callback.from_user.id
    bonus = BonusDAO(session)
    user_dao = RouletteUserDAO(session)

    message: str | None = None
    refresh_menu = False

    async with _transaction(session):
        next_at = await bonus.get_next_at(user_id)
        if next_at and next_at > now:
            remaining = max(1, int((next_at - now).total_seconds() // 3600))
            message = f"Доступно через ~{remaining} ч"
        else:
            refresh_menu = True
            if settings.BONUS_TYPE == "free_spin":
                await user_dao.adjust_free_spins(user_id, 1)
                message = texts.BONUS_GRANTED_FREE_SPIN
                logger.info("[Ruletka] daily_bonus spin tg_id=%s type=free_spin", user_id)
            else:
                amount = settings.BET_AMOUNT
                wallet = WalletService(session)
                await wallet.commit(
                    tg_id=user_id,
                    amount=amount,
                    spin_id=uuid4(),
                    jackpot_win=False,
                )
                message = texts.BONUS_GRANTED_COINS.format(
                    amount=_format_amount(amount),
                    currency=settings.CURRENCY_EMOJI,
                )
                logger.info(
                    "[Ruletka] daily_bonus spin tg_id=%s type=coins amount=%s",
                    user_id,
                    _format_amount(amount),
                )
            await bonus.set_next_at(
                user_id,
                next_at=now + timedelta(hours=settings.BONUS_COOLDOWN_H),
            )

    assert message is not None
    await callback.answer(message, show_alert=True)
    if refresh_menu:
        await _render_menu(callback, session)


async def _animate(
    message: Message,
    frames: list[tuple[str, str, str]],
    delays: list[float],
    jackpot_text: str,
) -> None:
    header = "<b>🎰 РУЛЕТКА КРУТИТСЯ</b>"
    status = f"Джекпот: {jackpot_text} {settings.CURRENCY_EMOJI}"
    for frame, delay in zip(frames, delays, strict=False):
        await asyncio.sleep(delay)
        try:
            frame_box = texts.format_slot_box(frame)
            await message.edit_text(f"{header}\n{frame_box}\n{status}")
        except TelegramBadRequest:
            break


class DailyLimitError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


async def _ensure_limits(
    session: AsyncSession,
    *,
    tg_id: int,
    bet: Decimal,
    expected_win: Decimal,
) -> None:
    today = date.today()
    spent, won = await get_daily_totals(session, tg_id=tg_id, day=today)
    if settings.DAILY_SPEND_LIMIT > 0 and spent + bet > settings.DAILY_SPEND_LIMIT:
        raise DailyLimitError(texts.DAILY_SPEND_LIMIT)
    if settings.DAILY_WIN_LIMIT > 0 and won + expected_win > settings.DAILY_WIN_LIMIT:
        raise DailyLimitError(texts.DAILY_WIN_LIMIT)


async def _log_metrics(session: AsyncSession) -> None:
    try:
        total_spins_result = await session.execute(select(func.count()).select_from(RouletteSpin))
        total_spins = int(total_spins_result.scalar_one())
        players_result = await session.execute(select(func.count()).select_from(RouletteUser))
        players_total = int(players_result.scalar_one())
        active_cutoff = datetime.utcnow() - timedelta(days=1)
        active_result = await session.execute(
            select(func.count()).where(RouletteUser.updated_at >= active_cutoff)
        )
        active_24h = int(active_result.scalar_one())
        won_sum_result = await session.execute(select(func.coalesce(func.sum(RouletteSpin.win), 0)))
        won_sum = Decimal(str(won_sum_result.scalar_one()))
        spent_est = settings.BET_AMOUNT * Decimal(total_spins)
        lost_fact = spent_est - won_sum
        free_spins_result = await session.execute(select(func.coalesce(func.sum(RouletteUser.free_spins), 0)))
        coupons_obligation = settings.BET_AMOUNT * Decimal(str(free_spins_result.scalar_one()))
        profit_fact = lost_fact - coupons_obligation
        jackpot_result = await session.execute(select(RouletteJackpot.amount).where(RouletteJackpot.id == 1))
        jackpot_value = jackpot_result.scalar_one_or_none() or module_state.base_jackpot
        logger.info(
            "[Ruletka][metrics] spins_total=%s players_total=%s active_24h=%s won_sum=%s spent_est=%s lost_fact=%s coupons_obligation=%s profit_fact=%s jackpot=%s",
            total_spins,
            players_total,
            active_24h,
            _format_amount(won_sum),
            _format_amount(spent_est),
            _format_amount(lost_fact),
            _format_amount(coupons_obligation),
            _format_amount(profit_fact),
            _format_amount(jackpot_value),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[Ruletka] Не удалось обновить метрики: %s", exc)


def _build_admin_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=texts.ADMIN_TOGGLE_MODULE,
            callback_data=RouletteAdminCallback(action="toggle").pack(),
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=texts.ADMIN_RESET_GUARANTEE,
            callback_data=RouletteAdminCallback(action="reset").pack(),
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=texts.ADMIN_SET_BASE_JACKPOT,
            callback_data=RouletteAdminCallback(action="set_base").pack(),
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=texts.ADMIN_FORCE_JACKPOT,
            callback_data=RouletteAdminCallback(action="force_jackpot").pack(),
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=texts.ADMIN_LAST_SPINS,
            callback_data=RouletteAdminCallback(action="last_spins").pack(),
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=texts.ADMIN_EXPORT_CSV,
            callback_data=RouletteAdminCallback(action="export_csv").pack(),
        )
    )
    builder.row(InlineKeyboardButton(text=texts.BUTTON_BACK, callback_data=ADMIN_PANEL_BACK))
    return builder.as_markup()


def _admin_cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=texts.BUTTON_BACK,
            callback_data=RouletteAdminCallback(action="menu").pack(),
        )
    )
    return builder.as_markup()


async def _compose_admin_overview(session: AsyncSession) -> tuple[str, InlineKeyboardMarkup]:
    jackpot = await JackpotDAO(session).get_amount()
    text = texts.render_admin_overview(
        enabled=_module_enabled(),
        base_jackpot=_format_amount(module_state.base_jackpot),
        jackpot=_format_amount(jackpot),
    )
    return text, _build_admin_keyboard()


@router.callback_query(RouletteAdminCallback.filter(F.action == "menu"), IsAdminFilter())
async def admin_menu_entry(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    text, markup = await _compose_admin_overview(session)
    if callback.message:
        await callback.message.edit_text(text, reply_markup=markup)


@router.callback_query(RouletteAdminCallback.filter(F.action == "toggle"), IsAdminFilter())
async def admin_toggle_module(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    new_value = not module_state.enabled
    await module_state.set_enabled(new_value)
    status_text = texts.ADMIN_STATUS_ON if new_value and settings.ENABLED else texts.ADMIN_STATUS_OFF
    logger.info("[Ruletka][admin] toggle_module tg_id=%s enabled=%s", callback.from_user.id, new_value)
    await callback.answer(texts.ADMIN_TOGGLE_RESULT.format(status=status_text))
    text, markup = await _compose_admin_overview(session)
    if callback.message:
        await callback.message.edit_text(text, reply_markup=markup)


@router.callback_query(RouletteAdminCallback.filter(F.action == "set_base"), IsAdminFilter())
async def admin_prompt_base(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(RouletteAdminStates.waiting_base_jackpot)
    await state.update_data(task="set_base")
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(texts.ADMIN_PROMPT_BASE, reply_markup=_admin_cancel_keyboard())


@router.callback_query(RouletteAdminCallback.filter(F.action == "reset"), IsAdminFilter())
async def admin_prompt_reset(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(RouletteAdminStates.waiting_tg_id)
    await state.update_data(task="reset")
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(texts.ADMIN_PROMPT_TG_ID, reply_markup=_admin_cancel_keyboard())


@router.callback_query(RouletteAdminCallback.filter(F.action == "force_jackpot"), IsAdminFilter())
async def admin_force_jackpot(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    async with _transaction(session):
        jackpot = await JackpotDAO(session).ensure(for_update=True)
        jackpot.amount = module_state.base_jackpot
        jackpot.updated_at = datetime.utcnow()
    _set_jackpot_cache(module_state.base_jackpot)
    logger.info("[Ruletka][admin] force_jackpot tg_id=%s", callback.from_user.id)
    text, markup = await _compose_admin_overview(session)
    await callback.answer(texts.ADMIN_FORCE_DONE)
    if callback.message:
        await callback.message.edit_text(text, reply_markup=markup)


@router.callback_query(RouletteAdminCallback.filter(F.action == "last_spins"), IsAdminFilter())
async def admin_last_spins(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    spins = await load_last_spins(session, limit=10)
    text = texts.render_admin_last_spins(spins, currency=settings.CURRENCY_EMOJI)
    if callback.message:
        await callback.message.edit_text(text, reply_markup=_admin_cancel_keyboard())


@router.callback_query(RouletteAdminCallback.filter(F.action == "export_csv"), IsAdminFilter())
async def admin_export_csv(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    spins = await load_last_spins(session, limit=100)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["spin_id", "tg_id", "bet", "win", "rarity", "prize", "jackpot_before", "jackpot_after", "created_at"])
    for spin in spins:
        writer.writerow(
            [
                str(spin.spin_id),
                spin.tg_id,
                _format_amount(spin.bet),
                _format_amount(spin.win),
                spin.rarity,
                spin.prize_code or "",
                _format_amount(spin.jackpot_before),
                _format_amount(spin.jackpot_after),
                spin.created_at.isoformat(sep=" ", timespec="seconds"),
            ]
        )
    payload = buffer.getvalue().encode("utf-8-sig")
    document = BufferedInputFile(file=payload, filename="roulette_spins.csv")
    await callback.answer(texts.ADMIN_EXPORT_READY)
    logger.info("[Ruletka][admin] export_csv tg_id=%s rows=%s", callback.from_user.id, len(spins))
    if callback.message:
        await callback.message.answer_document(document, caption=texts.ADMIN_EXPORT_CAPTION)
        overview_text, markup = await _compose_admin_overview(session)
        await callback.message.answer(overview_text, reply_markup=markup)


@router.message(RouletteAdminStates.waiting_tg_id, IsAdminFilter())
async def admin_handle_tg_id(message: Message, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    task = data.get("task")
    tg_id_text = message.text or ""
    try:
        tg_id = int(tg_id_text.strip())
    except (TypeError, ValueError):
        await message.answer(texts.ADMIN_INVALID_INPUT)
        return

    if task == "reset":
        async with _transaction(session):
            user = await RouletteUserDAO(session).get_or_create(tg_id)
            user.guarantee_counter = 0
            user.updated_at = datetime.utcnow()
        _LAST_SPIN_AT.pop(tg_id, None)
        logger.info("[Ruletka][admin] reset_guarantee admin=%s target=%s", message.from_user.id, tg_id)
        await message.answer(texts.ADMIN_RESET_DONE.format(tg_id=tg_id))

    await state.clear()
    overview_text, markup = await _compose_admin_overview(session)
    await message.answer(overview_text, reply_markup=markup)


@router.message(RouletteAdminStates.waiting_base_jackpot, IsAdminFilter())
async def admin_handle_base_jackpot(message: Message, session: AsyncSession, state: FSMContext) -> None:
    raw_value = (message.text or "").strip().replace(",", ".")
    try:
        new_base = Decimal(raw_value)
    except Exception:  # noqa: BLE001
        await message.answer(texts.ADMIN_INVALID_INPUT)
        return
    new_base = new_base.quantize(Decimal("0.01"))
    await module_state.set_base_jackpot(new_base)
    async with _transaction(session):
        jackpot = await JackpotDAO(session).ensure(for_update=True)
        if Decimal(jackpot.amount or 0) < new_base:
            jackpot.amount = new_base
        jackpot.updated_at = datetime.utcnow()
    _set_jackpot_cache(new_base)
    logger.info("[Ruletka][admin] base_jackpot_updated admin=%s value=%s", message.from_user.id, _format_amount(new_base))
    await message.answer(texts.ADMIN_BASE_UPDATED.format(amount=_format_amount(new_base)))
    await state.clear()
    overview_text, markup = await _compose_admin_overview(session)
    await message.answer(overview_text, reply_markup=markup)


@router.message(Command("ruletka"))
async def command_ruletka(message: Message, session: AsyncSession) -> None:
    if not _module_enabled():
        await message.answer(texts.MODULE_DISABLED)
        return
    await _render_menu(message, session)


@router.callback_query(F.data == MENU_CALLBACK)
async def menu_callback(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    await _render_menu(callback, session)


@router.callback_query(F.data == PRIZES_CALLBACK)
async def prizes_callback(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    await _show_prizes(callback)


@router.callback_query(F.data == STATS_CALLBACK)
async def stats_callback(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    await _show_stats(callback, session)


@router.callback_query(F.data.startswith(LEADERBOARD_CALLBACK))
async def leaderboard_callback(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    scope = _extract_scope_from_payload(callback.data)
    await _show_leaderboard(callback, session, scope=scope)


@router.callback_query(F.data.startswith(LEADERBOARD_REFRESH_CALLBACK))
async def leaderboard_refresh_callback(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    scope = _extract_scope_from_payload(callback.data)
    await _show_leaderboard(callback, session, scope=scope)


@router.callback_query(F.data == BONUS_CALLBACK)
async def bonus_callback(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    await _claim_bonus(callback, session)


@router.callback_query(F.data == NOTIFY_TOGGLE_CALLBACK)
async def notify_toggle_callback(callback: CallbackQuery, session: AsyncSession) -> None:
    if not (settings.ALLOW_USER_NOTIFY_TOGGLE and settings.NOTIFICATIONS_ENABLED):
        await callback.answer()
        return

    tg_id = callback.from_user.id
    try:
        async with _transaction(session):
            current = await get_notify_enabled(session, tg_id)
            await set_notify_enabled(session, tg_id, not current)
            new_value = not current
    except Exception as exc:  # noqa: BLE001
        logger.exception("[Ruletka] Ошибка переключения уведомлений: %s", exc)
        await callback.answer(texts.ERROR_MESSAGE, show_alert=True)
        return

    status_text = texts.NOTIFY_ENABLED if new_value else texts.NOTIFY_DISABLED
    await callback.answer(status_text, show_alert=True)
    await _render_menu(callback, session)


@router.callback_query(F.data == SPIN_CALLBACK)
async def spin_callback(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _module_enabled():
        await callback.answer(texts.MODULE_DISABLED, show_alert=True)
        return

    tg_id = callback.from_user.id
    lock = _get_lock(tg_id)
    if lock.locked():
        await callback.answer(texts.CONCURRENT_SPIN, show_alert=True)
        return

    now = time.monotonic()
    last = _LAST_SPIN_AT.get(tg_id, 0)
    if now - last < settings.ANTI_SPAM_COOLDOWN_S:
        await callback.answer(texts.COOLDOWN_MESSAGE, show_alert=True)
        return

    await callback.answer()
    _LAST_SPIN_AT[tg_id] = now

    async with lock:
        message = callback.message
        if message is None:
            return
        try:
            await message.edit_text(texts.SPIN_PREPARING)
        except TelegramBadRequest:
            pass

        seed, rng = _build_seed(tg_id)
        spin_id = uuid4()
        wallet = WalletService(session)
        user_dao = RouletteUserDAO(session)
        jackpot_dao = JackpotDAO(session)
        leaderboard = LeaderboardDAO(session)

        start_time = time.perf_counter()
        balance_after: Decimal | None = None
        spin_row: RouletteSpin | None = None
        win_amount = Decimal("0")
        rarity_name = "Common"
        prize_code: str | None = None
        prize_title = "—"
        jackpot_before = Decimal("0")
        jackpot_after = Decimal("0")
        free_spins_after = 0
        animation_frames: list[tuple[str, str, str]] = []
        animation_delays: list[float] = []
        final_icons: tuple[str, str, str] | None = None
        is_jackpot = False
        user: RouletteUser | None = None
        spin_timestamp: datetime | None = None

        wallet_mode_http = settings.WALLET_MODE.lower() == "http"
        needs_http_rollback = False
        bet_amount = settings.BET_AMOUNT
        new_spin = True

        logger.info(
            "[Ruletka] spin_start spin_id=%s tg_id=%s bet=%s",
            spin_id,
            tg_id,
            _format_amount(bet_amount),
        )

        try:
            async with _transaction(session):
                user = await user_dao.get_or_create(tg_id)
                free_spins = user.free_spins or 0
                use_free_spin = free_spins > 0
                if use_free_spin:
                    bet_amount = Decimal("0")
                    await user_dao.adjust_free_spins(tg_id, -1)
                else:
                    bet_amount = settings.BET_AMOUNT

                reservation: WalletReservation | None = None
                if bet_amount > 0:
                    reservation = await wallet.reserve(tg_id=tg_id, amount=bet_amount, spin_id=spin_id)
                    if reservation.already_processed and reservation.existing_spin is not None:
                        spin_row = reservation.existing_spin
                        win_amount = Decimal(spin_row.win or 0)
                        rarity_name = spin_row.rarity
                        prize_code = spin_row.prize_code
                        prize_title = _resolve_prize_title(prize_code)
                        jackpot_before = Decimal(spin_row.jackpot_before)
                        jackpot_after = Decimal(spin_row.jackpot_after)
                        _set_jackpot_cache(jackpot_after)
                        balance_after = reservation.balance_after
                        seed_rng = random.Random()
                        if spin_row.seed:
                            try:
                                seed_rng = random.Random(int(spin_row.seed, 16))
                            except ValueError:
                                seed_rng = random.Random()
                        final_icons = _resolve_final_icons(seed_rng, prize_code)
                        is_jackpot = bool(prize_code and prize_code.upper() == "JACKPOT")
                        new_spin = False
                        spin_timestamp = spin_row.created_at
                    else:
                        balance_after = reservation.balance_after
                        if wallet_mode_http and reservation:
                            needs_http_rollback = True

                if new_spin:
                    threshold = settings.GUARANTEE_VIP if user.vip_active else settings.GUARANTEE_BASE
                    guarantee_triggered = user.guarantee_counter + 1 >= threshold
                    min_rarity = settings.GUARANTEE_MIN_RARITY if guarantee_triggered else None
                    rarity, rarity_roll = _pick_rarity(rng, min_rarity=min_rarity)
                    prize, prize_roll = _pick_prize(rarity, rng)
                    rarity_name = rarity.name
                    prize_code = prize.code
                    prize_title = prize.title
                    prize_amount = prize.amount

                    jackpot_state = await jackpot_dao.ensure(for_update=True)
                    jackpot_before = Decimal(jackpot_state.amount or module_state.base_jackpot)
                    jackpot_increment = (bet_amount * settings.JACKPOT_FEE).quantize(Decimal("0.01"))
                    jackpot_pool = jackpot_before + jackpot_increment

                    is_jackpot = False
                    if isinstance(prize_amount, str) and prize_amount.upper() == "JACKPOT":
                        win_amount = jackpot_pool
                        jackpot_after = module_state.base_jackpot
                        is_jackpot = True
                    else:
                        win_amount = Decimal(prize_amount)
                        jackpot_after = jackpot_pool

                    await _ensure_limits(session, tg_id=tg_id, bet=bet_amount, expected_win=win_amount)

                    jackpot_state.amount = jackpot_after
                    jackpot_state.updated_at = datetime.utcnow()

                    if guarantee_triggered:
                        logger.info(
                            "[Ruletka] guarantee_trigger spin_id=%s tg_id=%s threshold=%s forced_rarity=%s",
                            spin_id,
                            tg_id,
                            threshold,
                            min_rarity,
                        )

                    commit_balance = await wallet.commit(
                        tg_id=tg_id,
                        amount=win_amount,
                        spin_id=spin_id,
                        jackpot_win=is_jackpot,
                        bet=bet_amount,
                    )
                    if commit_balance is not None:
                        balance_after = commit_balance
                    if wallet_mode_http:
                        needs_http_rollback = False
                    user = await user_dao.increment_spin(
                        tg_id,
                        win_amount=win_amount,
                        jackpot_win=is_jackpot,
                        non_empty_prize=win_amount > 0 or (prize_code and prize_code != "NONE"),
                    )
                    await leaderboard.add_win(tg_id=tg_id, amount=win_amount, day=date.today())

                    record = SpinRecord(
                        spin_id=spin_id,
                        tg_id=tg_id,
                        bet=bet_amount,
                        win=win_amount,
                        rarity=rarity_name,
                        prize_code=prize_code,
                        seed=seed,
                        jackpot_before=jackpot_before,
                        jackpot_after=jackpot_after,
                        chat_id=message.chat.id,
                        message_id=message.message_id,
                        created_at=datetime.utcnow(),
                    )
                    spin_row = await record_spin(session, record)
                    spin_timestamp = record.created_at

                    final_icons = _resolve_final_icons(rng, prize_code)
                    animation_frames, animation_delays = _build_animation(rng, final_icons)
                    _set_jackpot_cache(jackpot_after)

                    logger.info(
                        "[Ruletka] rng spin_id=%s seed=%s rarity_roll=%.4f prize_roll=%.4f rarity=%s prize=%s",
                        spin_id,
                        seed,
                        rarity_roll,
                        prize_roll,
                        rarity_name,
                        prize_code,
                    )
                if spin_timestamp is not None:
                    await touch_last_spin(session, tg_id, when=spin_timestamp)
                free_spins_after = await user_dao.get_free_spins(tg_id)

        except InsufficientFunds:
            if wallet_mode_http and needs_http_rollback and bet_amount > 0:
                try:
                    await wallet.rollback(tg_id=tg_id, amount=bet_amount, spin_id=spin_id)
                except Exception:  # noqa: BLE001
                    logger.warning("[Ruletka] Не удалось откатить резерв кошелька", exc_info=True)
            await _show_insufficient_funds(callback)
            return
        except DailyLimitError as exc:
            if wallet_mode_http and needs_http_rollback and bet_amount > 0:
                try:
                    await wallet.rollback(tg_id=tg_id, amount=bet_amount, spin_id=spin_id)
                except Exception:  # noqa: BLE001
                    logger.warning("[Ruletka] Ошибка отката кошелька", exc_info=True)
            await callback.answer(exc.message, show_alert=True)
            await _render_menu(callback, session)
            return
        except Exception as exc:  # noqa: BLE001
            if wallet_mode_http and needs_http_rollback and bet_amount > 0:
                try:
                    await wallet.rollback(tg_id=tg_id, amount=bet_amount, spin_id=spin_id)
                except Exception:  # noqa: BLE001
                    logger.warning("[Ruletка] Не удалось откатить", exc_info=True)
            logger.exception("[Ruletka] Ошибка при обработке спина: %s", exc)
            await callback.answer(texts.ERROR_MESSAGE, show_alert=True)
            await _render_menu(callback, session)
            return

        if spin_row is None:
            await _render_menu(callback, session)
            return

        vip_status = bool(user.vip_active) if user is not None else False

        if final_icons is None:
            if animation_frames:
                final_icons = animation_frames[-1]
            else:
                seed_rng = random.Random()
                if spin_row.seed:
                    try:
                        seed_rng = random.Random(int(spin_row.seed, 16))
                    except ValueError:
                        seed_rng = random.Random()
                final_icons = _resolve_final_icons(seed_rng, prize_code)

        if new_spin and animation_frames:
            await _animate(
                message,
                animation_frames,
                animation_delays,
                _format_amount(jackpot_after),
            )

        if balance_after is None:
            try:
                balance_after = await get_user_balance(session, tg_id)
            except Exception:  # noqa: BLE001
                balance_after = None

        balance_text = "—" if balance_after is None else _format_amount(balance_after)
        prize_icon = settings.PRIZE_ICONS.get((prize_code or "").upper(), "🎁")
        rarity_icon = settings.RARITY_EMOJI.get(rarity_name, "⚪️")
        win_text = _format_amount(win_amount)
        if (prize_code or "").upper() == "NONE" or win_amount == 0:
            comment_line = texts.RESULT_COMMENT_EMPTY
        elif is_jackpot:
            comment_line = texts.RESULT_COMMENT_JACKPOT.format(
                amount=win_text,
                currency=settings.CURRENCY_EMOJI,
            )
        else:
            comment_line = texts.RESULT_COMMENT_WIN.format(
                amount=win_text,
                currency=settings.CURRENCY_EMOJI,
            )

        info_block = "\n".join(
            (
                f"{rarity_icon} Редкость: <b>{rarity_name}</b>",
                f"{prize_icon} Приз: {prize_title}",
                comment_line,
            )
        )

        summary_block = texts.SPIN_RESULT_TEMPLATE.format(
            win=win_text,
            balance=balance_text,
            jackpot=_format_amount(jackpot_after),
            currency=settings.CURRENCY_EMOJI,
        )

        status_line = (
            f"👑 VIP статус: {'Активен' if vip_status else 'Нет'} | "
            f"💰 Джекпот: {_format_amount(jackpot_after)} {settings.CURRENCY_EMOJI} | "
            f"🎟️ Бесплатных: {free_spins_after} | ↩️ Профиль"
        )

        result_text = "\n\n".join(
            (
                texts.RESULT_TITLE,
                texts.format_result_box(final_icons),
                info_block,
                summary_block,
            )
        )
        result_text = f"{result_text}\n\n{status_line}"

        duration_ms = (time.perf_counter() - start_time) * 1000
        logger.info(
            "[Ruletka] spin_id=%s tg_id=%s bet=%s win=%s rarity=%s prize=%s jackpot_before=%s jackpot_after=%s time_ms=%.2f seed=%s",
            spin_row.spin_id,
            tg_id,
            _format_amount(spin_row.bet),
            _format_amount(spin_row.win),
            spin_row.rarity,
            spin_row.prize_code,
            _format_amount(spin_row.jackpot_before),
            _format_amount(spin_row.jackpot_after),
            duration_ms,
            seed,
        )

        try:
            await message.edit_text(result_text, reply_markup=_main_keyboard(free_spins_after, settings.BET_AMOUNT))
        except TelegramBadRequest:
            await message.answer(result_text, reply_markup=_main_keyboard(free_spins_after, settings.BET_AMOUNT))

        if new_spin:
            await _log_metrics(session)


async def start_menu_hook(**_: Any):
    if not _module_enabled():
        return None
    return insert_hook_buttons(
        {"button": InlineKeyboardButton(text=texts.BUTTON_START, callback_data=MENU_CALLBACK)}
    )


async def profile_menu_hook(
    *,
    session: AsyncSession | None = None,
    tg_id: int | None = None,
    chat_id: int | None = None,
    **_: Any,
):
    if not _module_enabled():
        return None

    # Убраны кнопки "🏆 Топ" и "🔔/🔕 Уведомления" из профиля.
    # Оставлена только кнопка входа в рулетку.
    operations: list[dict[str, Any]] = [
        {
            "after": "balance",
            "button": InlineKeyboardButton(
                text=texts.BUTTON_PROFILE_ENTRY,
                callback_data=MENU_CALLBACK,
            ),
        },
    ]

    return insert_hook_buttons(operations)


async def pay_menu_buttons_hook(bundles: Iterable[Any] | None = None, **_: Any):
    names = _extract_bundle_names(bundles)
    if not names:
        return None
    if any("бонус" in name for name in names):
        return insert_hook_buttons(
            {
                "button": InlineKeyboardButton(
                    text=texts.BUTTON_PAY_PROMO,
                    callback_data=MENU_CALLBACK,
                )
            }
        )
    return None


async def view_key_menu_hook(**_: Any):
    if not _module_enabled():
        return None
    return insert_hook_buttons(
        {"button": InlineKeyboardButton(text=texts.BUTTON_KEY_MENU, callback_data=MENU_CALLBACK)}
    )


async def admin_panel_hook(**_: Any):
    button = InlineKeyboardButton(text=texts.BUTTON_ADMIN_PANEL, callback_data=RouletteAdminCallback(action="menu").pack())
    return insert_hook_buttons({"button": button})


async def periodic_notifications(bot, session: AsyncSession, keys, **kwargs):  # noqa: ANN001, D417
    if not settings.NOTIFICATIONS_ENABLED:
        logger.debug("[Ruletka][notify] Отключено флагом — пропуск")
        return None

    notifications: list[dict[str, Any]] = []
    per_channel: dict[str, int] = defaultdict(int)
    users_result = await session.execute(select(RouletteUser))
    users: list[RouletteUser] = users_result.scalars().all()
    if not users:
        logger.debug("[Ruletka][notify] Пользователей нет — отправлять нечего")
        return None

    prefs_result = await session.execute(select(RoulettePreference))
    prefs_map = {pref.tg_id: pref for pref in prefs_result.scalars()}

    active_ids: set[int] = set()
    if settings.NOTIFY_ONLY_ACTIVE:
        active_cutoff = datetime.utcnow() - timedelta(days=settings.ACTIVE_WINDOW_DAYS)
        active_ids = set(await get_active_users(session, active_cutoff))

    def _notifications_allowed(user: RouletteUser) -> bool:
        pref = prefs_map.get(user.tg_id)
        if pref is not None and pref.notify_enabled is False:
            return False
        if settings.NOTIFY_ONLY_ACTIVE and user.tg_id not in active_ids:
            return False
        return True

    eligible_users = [user for user in users if _notifications_allowed(user)]

    threshold_vip = settings.GUARANTEE_VIP
    threshold_base = settings.GUARANTEE_BASE
    for user in eligible_users:
        threshold = threshold_vip if user.vip_active else threshold_base
        if user.guarantee_counter >= threshold - 1:
            if not _NOTIFICATION_QUOTA.allow(user.tg_id, "guarantee", settings.PERIODIC_MAX_PER_USER):
                continue
            markup = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🎰 Открыть рулетку", callback_data="ruletka:menu")]
                ]
            )
            notifications.append(
                {
                    "tg_id": user.tg_id,
                    "text": texts.PERIODIC_GUARANTEE,
                    "jitter": (settings.PERIODIC_JITTER_MIN_S, settings.PERIODIC_JITTER_MAX_S),
                    "reply_markup": markup,
                    "channel": "guarantee",
                }
            )
            per_channel["guarantee"] += 1


    jackpot = await JackpotDAO(session).get_amount()
    if jackpot >= settings.JACKPOT_NOTIFY_THRESHOLD:
        for user in eligible_users:
            if not _NOTIFICATION_QUOTA.allow(user.tg_id, "jackpot", settings.PERIODIC_MAX_PER_USER):
                continue
            markup = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🎰 Открыть рулетку", callback_data="ruletka:menu")]
                ]
            )
            notifications.append(
                {
                    "tg_id": user.tg_id,
                    "text": texts.PERIODIC_BIG_JACKPOT.format(
                        jackpot=_format_amount(jackpot),
                        currency=settings.CURRENCY_EMOJI,
                    ),
                    "jitter": (settings.PERIODIC_JITTER_MIN_S, settings.PERIODIC_JITTER_MAX_S),
                    "reply_markup": markup,
                    "channel": "jackpot",
                }
            )
            per_channel["jackpot"] += 1

    cutoff = datetime.utcnow() - timedelta(days=settings.INACTIVE_NOTIFY_DAYS)
    for user in users:
        if user.updated_at and user.updated_at < cutoff:
            if not _notifications_allowed(user):
                continue
            if not _NOTIFICATION_QUOTA.allow(user.tg_id, "inactive", settings.PERIODIC_MAX_PER_USER):
                continue
            markup = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🎰 Открыть рулетку", callback_data="ruletka:menu")]
                ]
            )
            notifications.append(
                {
                    "tg_id": user.tg_id,
                    "text": texts.PERIODIC_RETURN,
                    "jitter": (settings.PERIODIC_JITTER_MIN_S, settings.PERIODIC_JITTER_MAX_S),
                    "reply_markup": markup,
                    "channel": "inactive",
                }
            )
            per_channel["inactive"] += 1

    # 🔔 Ежедневный бонус: уведомляем только тех, кто уже крутил рулетку
    if settings.BONUS_ENABLED and getattr(settings, "BONUS_NOTIFY_ENABLED", True):
        now = datetime.utcnow()
        for user in eligible_users:
            # Только пользователи, у которых были спины
            if (user.spins_total or 0) <= 0:
                pref = prefs_map.get(user.tg_id)
                if pref is None or pref.last_spin_at is None:
                    continue

            next_at = user.bonus_next_at
            if next_at is None or next_at <= now:
                if not _NOTIFICATION_QUOTA.allow(user.tg_id, "bonus", settings.PERIODIC_MAX_PER_USER):
                    continue

                # Создаём кнопку для перехода в рулетку
                markup = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="🎰 Открыть рулетку", callback_data="ruletka:menu")]
                    ]
                )
                notifications.append(
                    {
                        "tg_id": user.tg_id,
                        "text": getattr(texts, "PERIODIC_BONUS_READY", "Доступен ежедневный бонус! 🎁"),
                        "jitter": (settings.PERIODIC_JITTER_MIN_S, settings.PERIODIC_JITTER_MAX_S),
                        "reply_markup": markup,
                        "channel": "bonus",
                    }
                )
                per_channel["bonus"] += 1

    # === Отправка, как в «рабочем» модуле ===
    if not notifications:
        logger.debug("[Ruletka][notify] Пусто — отправлять нечего")
        return None

    # лог: сколько всего и по каналам
    try:
        total = len(notifications)
        sample_ids = [n["tg_id"] for n in notifications[:10]]
        logger.info(
            "[Ruletka][notify] Собрано уведомлений: total=%d; breakdown=%s; примеры tg_id=%s",
            total,
            dict(per_channel),
            sample_ids,
        )
    except Exception:
        logger.debug("[Ruletka][notify] Не удалось сформировать лог по пачке", exc_info=True)

    # Подготовка payload под send_messages_with_limit
    payload: list[dict[str, Any]] = []
    for item in notifications:
        payload.append(
            {
                "tg_id": item["tg_id"],
                "text": item["text"],
                "keyboard": item.get("reply_markup"),
                "jitter": item.get("jitter"),
            }
        )

    try:
        results = await send_messages_with_limit(
            bot,
            payload,
            session=session,
            source_file="ruletka",
        )
        sent = sum(1 for r in results if r)
        logger.info("[Ruletka][notify] Отправлено: %d из %d", sent, len(payload))
    except Exception as exc:  # noqa: BLE001
        logger.exception("[Ruletka][notify] Ошибка отправки: %s", exc)
    return None


register_hook("start_menu", start_menu_hook)
register_hook("profile_menu", profile_menu_hook)
register_hook("pay_menu_buttons", pay_menu_buttons_hook)
# register_hook("view_key_menu", view_key_menu_hook)
register_hook("admin_panel", admin_panel_hook)
register_hook("periodic_notifications", periodic_notifications)
