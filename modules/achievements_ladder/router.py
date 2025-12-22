from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from handlers.profile import process_callback_view_profile
from hooks.hooks import register_hook
from logger import logger

from . import (
    db as achv_db,
    keyboards,
    services,
    settings,
    texts,
)


router = Router(name="achievements_ladder")


def _should_show_button(kwargs: dict[str, Any]) -> bool:
    visibility = settings.ACHV.get("BUTTON_VISIBILITY", {})
    mode = str(visibility.get("MODE", "ALL")).upper()
    if mode != "RESTRICTED":
        return True
    if kwargs.get("admin"):
        return True
    allowed_ids: set[int] = set()
    for tg_id in visibility.get("ALLOWED_IDS", []):
        try:
            allowed_ids.add(int(tg_id))
        except (TypeError, ValueError):
            continue
    user_id = _extract_tg_id(kwargs)
    if user_id is None:
        return False
    try:
        return int(user_id) in allowed_ids
    except (TypeError, ValueError):
        return False


def _extract_tg_id(kwargs: dict[str, Any]) -> int | None:
    for key in ("chat_id", "user_id", "tg_id"):
        if key in kwargs and kwargs[key] is not None:
            return kwargs[key]
    event = kwargs.get("event")
    if event is not None:
        from_user = getattr(event, "from_user", None)
        if from_user and getattr(from_user, "id", None) is not None:
            return from_user.id
        chat = getattr(event, "chat", None)
        if chat and getattr(chat, "id", None) is not None:
            return chat.id
    message = kwargs.get("message")
    if message is not None:
        chat = getattr(message, "chat", None)
        if chat and getattr(chat, "id", None) is not None:
            return chat.id
    return None


async def start_menu_hook(**kwargs: Any):
    if not _should_show_button(kwargs):
        return None
    return {"button": InlineKeyboardButton(text="🎯 Достижения", callback_data="achv|open")}


async def profile_menu_hook(**kwargs: Any):
    if not _should_show_button(kwargs):
        return None
    return {
        "after": "balance",
        "button": InlineKeyboardButton(text="🎯 Достижения", callback_data="achv|open"),
    }


register_hook("start_menu", start_menu_hook)
register_hook("profile_menu", profile_menu_hook)


async def periodic_notifications_hook(
    bot: Any,
    session: AsyncSession | None = None,
    sessionmaker: async_sessionmaker | None = None,
    **_: Any,
):
    if session is not None:
        await services.periodic_notifications(bot, session=session)
        return

    if sessionmaker is not None:
        await services.periodic_notifications(bot, sessionmaker=sessionmaker)
        return

    raise ValueError("`session` or `sessionmaker` must be provided")


cfg = settings.ACHV["NOTIFY"]
start_msk = datetime.now(ZoneInfo("Europe/Moscow")).replace(
    hour=cfg["HOUR_MSK"], minute=cfg["MINUTE"], second=0, microsecond=0
)
periodic_notifications_hook.start_at = start_msk.astimezone(ZoneInfo("UTC"))
periodic_notifications_hook.period = cfg["PERIOD_HOURS"] * 3600


register_hook("periodic_notifications", periodic_notifications_hook)


async def daily_visit_hook(tg_id: int, session: AsyncSession, **_: Any):
    await achv_db.log_daily_visit(session, tg_id)


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_payment_tg_id(payment: Any) -> int | None:
    if payment is None:
        return None
    for key in ("tg_id", "user_id", "chat_id"):
        if isinstance(payment, dict) and key in payment:
            return _coerce_int(payment[key])
        attr = getattr(payment, key, None)
        if attr is not None:
            return _coerce_int(attr)
    return None


def _extract_user_details(
    username: str | None,
    first_name: str | None,
    user: Any,
) -> tuple[str | None, str | None]:
    if user is None:
        return username, first_name

    user_mapping = user if isinstance(user, dict) else None

    if username is None:
        username = (
            getattr(user, "username", None)
            if user_mapping is None
            else user_mapping.get("username")
        )

    if first_name is None:
        first_name = (
            getattr(user, "first_name", None)
            if user_mapping is None
            else user_mapping.get("first_name")
        )

    return username, first_name


async def payment_hook(
    session: AsyncSession,
    tg_id: int | None = None,
    bot: Any | None = None,
    username: str | None = None,
    first_name: str | None = None,
    payment: Any | None = None,
    user: Any | None = None,
    **kwargs: Any,
):
    if tg_id is None:
        tg_id = _extract_payment_tg_id(payment)

    if tg_id is None:
        tg_id = _extract_tg_id(kwargs)

    if tg_id is None:
        logger.warning("[achievements_ladder] payment_hook: unable to resolve tg_id")
        return

    username, first_name = _extract_user_details(username, first_name, user)

    steps = await services.calculate_steps(session, tg_id)
    await services.check_thresholds_and_grant(
        session, tg_id, steps, bot=bot, username=username, first_name=first_name
    )


async def referral_hook(
    tg_id: int,
    session: AsyncSession,
    bot: Any | None = None,
    username: str | None = None,
    first_name: str | None = None,
    **_: Any,
):
    steps = await services.calculate_steps(session, tg_id)
    await services.check_thresholds_and_grant(
        session, tg_id, steps, bot=bot, username=username, first_name=first_name
    )


register_hook("daily_visit", daily_visit_hook)
register_hook("payment_success", payment_hook)
register_hook("referral_bound", referral_hook)


async def _edit_message(
    callback: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
) -> None:
    """Edit callback message text/caption or send a new message."""

    message = callback.message
    if message is None:
        return

    if message.text is not None:
        await message.edit_text(text, reply_markup=reply_markup)
        return

    if message.caption is not None:
        await message.edit_caption(caption=text, reply_markup=reply_markup)
        return

    await message.answer(text, reply_markup=reply_markup)


@router.callback_query(F.data == "achv|open")
async def open_progress(callback: CallbackQuery, session: AsyncSession):
    tg_id = callback.from_user.id
    steps = await services.calculate_steps(session, tg_id)
    claimed = await services.get_claimed_steps(session, tg_id)
    claimable = services.next_claimable_threshold(steps, claimed)
    if claimable:
        remain = max(0, claimable["steps"] - steps)
    else:
        upcoming = services.next_unreached_threshold(steps, claimed)
        remain = max(0, upcoming["steps"] - steps) if upcoming else 0
    channel_claimed = await achv_db.has_channel_bonus(session, tg_id)
    text = texts.PROGRESS.format(steps=steps, remain=remain)
    if not channel_claimed:
        text += f"\n\n{texts.CHANNEL_PROMPT}"
    text += f"\n\n{texts.HOWTO_SHORT}"
    kb = keyboards.progress_keyboard(claimable, channel_claimed).as_markup()
    await _edit_message(callback, text, kb)
    await achv_db.update_progress_anchor(session, tg_id)


@router.callback_query(F.data == "achv|rewards")
async def show_rewards(callback: CallbackQuery, session: AsyncSession):
    tg_id = callback.from_user.id
    steps = await services.calculate_steps(session, tg_id)
    claimed = await services.get_claimed_steps(session, tg_id)
    text = texts.format_rewards(settings.ACHV["THRESHOLDS"], steps, claimed)
    kb = keyboards.rewards_keyboard().as_markup()
    await _edit_message(callback, text, kb)


@router.callback_query(F.data == "achv|breakdown")
async def show_breakdown(callback: CallbackQuery, session: AsyncSession):
    tg_id = callback.from_user.id
    breakdown = await services.calculate_steps_breakdown(session, tg_id)
    text = texts.format_breakdown(breakdown)
    kb = keyboards.back_to_progress_keyboard().as_markup()
    await _edit_message(callback, text, kb)


@router.callback_query(F.data.startswith("achv|claim|"))
async def claim_reward(callback: CallbackQuery, session: AsyncSession):
    tg_id = callback.from_user.id
    steps = await services.calculate_steps(session, tg_id)
    threshold = await services.check_thresholds_and_grant(
        session,
        tg_id,
        steps,
        bot=callback.bot,
        username=callback.from_user.username,
        first_name=callback.from_user.first_name,
    )
    if threshold:
        await callback.answer(texts.REWARD_CLAIMED.format(steps=threshold["steps"]), show_alert=True)
    else:
        await callback.answer(texts.NOTHING_TO_CLAIM, show_alert=True)
    await open_progress(callback, session)


@router.callback_query(F.data == "achv|check_channel")
async def check_channel(callback: CallbackQuery, session: AsyncSession):
    tg_id = callback.from_user.id
    member = await callback.bot.get_chat_member(settings.ACHV["ANNOUNCE_CHANNEL_ID"], tg_id)
    if member.status in {"member", "administrator", "creator"}:
        if not await achv_db.has_channel_bonus(session, tg_id):
            await achv_db.set_channel_bonus(session, tg_id)
            await callback.answer(texts.CHANNEL_BONUS_OK, show_alert=True)
        else:
            await callback.answer(texts.CHANNEL_ALREADY, show_alert=True)
    else:
        await callback.answer(texts.CHANNEL_NOT_JOINED, show_alert=True)
    await open_progress(callback, session)

@router.callback_query(F.data == "achv|howto")
async def show_howto(callback: CallbackQuery):
    await _edit_message(callback, texts.HOWTO_FULL, keyboards.top_keyboard().as_markup())

@router.callback_query(F.data == "achv|top")
async def show_top(callback: CallbackQuery, session: AsyncSession):
    top = await services.get_top(session)
    text = texts.format_top(top, 5)
    kb = keyboards.top_keyboard().as_markup()
    await _edit_message(callback, text, kb)


@router.callback_query(F.data == "achv|back")
async def back_to_profile(callback: CallbackQuery, state: FSMContext, session: AsyncSession, admin: bool):
    await process_callback_view_profile(callback.message, state, admin, session)
