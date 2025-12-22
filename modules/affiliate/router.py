"""Маршрутизатор модуля партнёрской программы."""

from __future__ import annotations

import io
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from dataclasses import dataclass

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

import qrcode

from database import add_referral, add_user, check_user_exists, get_referral_by_referred_id
from database.models import Referral
from handlers.admin.panel.keyboard import AdminPanelCallback
from handlers.profile import process_callback_view_profile
from handlers.utils import edit_or_send_message
from hooks.hooks import register_hook
from logger import logger

from . import db, settings, texts
from .models import AffiliateAccount, AffiliateBalance


router = Router(name="affiliate")


class AffiliateStates(StatesGroup):
    wait_card_number = State()
    wait_card_confirm = State()
    wait_withdraw_amount = State()
    wait_withdraw_confirm = State()
    wait_admin_tg_id = State()


@dataclass(slots=True)
class _PartnerStatFallback:
    tg_id: int
    referrals: int
    available: Decimal
    hold: Decimal


async def _fetch_partner_stats(
    session: AsyncSession,
    *,
    page: int,
    page_size: int,
) -> tuple[list[object], int, int]:
    """Return partner statistics using db helper or internal fallback."""

    fetcher = getattr(db, "list_partner_stats", None)
    if callable(fetcher):
        return await fetcher(session, page=page, page_size=page_size)

    partner_stat_cls = getattr(db, "PartnerStat", None) or _PartnerStatFallback

    page = max(1, page)
    page_size = max(1, page_size)

    balance_subq = (
        select(
            AffiliateBalance.tg_id.label("tg_id"),
            AffiliateBalance.available_amount.label("available"),
            AffiliateBalance.hold_amount.label("hold"),
        )
        .subquery()
    )
    count_referrals = func.count(Referral.referred_tg_id)
    available_amount = func.coalesce(balance_subq.c.available, 0)
    hold_amount = func.coalesce(balance_subq.c.hold, 0)

    base_query = (
        select(
            AffiliateAccount.tg_id.label("tg_id"),
            count_referrals.label("referrals"),
            available_amount.label("available"),
            hold_amount.label("hold"),
        )
        .select_from(AffiliateAccount)
        .join(balance_subq, balance_subq.c.tg_id == AffiliateAccount.tg_id, isouter=True)
        .join(Referral, Referral.referrer_tg_id == AffiliateAccount.tg_id, isouter=True)
        .group_by(AffiliateAccount.tg_id, balance_subq.c.available, balance_subq.c.hold)
        .having(or_(count_referrals > 0, available_amount + hold_amount > 0))
        .order_by(count_referrals.desc(), AffiliateAccount.tg_id.asc())
    )

    stats_subq = base_query.subquery()
    total_result = await session.execute(select(func.count()).select_from(stats_subq))
    total = total_result.scalar_one_or_none() or 0

    if total == 0:
        return [], 0, 1

    total_pages = max(1, (total + page_size - 1) // page_size)
    current_page = min(page, total_pages)
    offset = (current_page - 1) * page_size

    result = await session.execute(select(stats_subq).offset(offset).limit(page_size))
    rows = result.mappings().all()

    stats = [
        partner_stat_cls(
            tg_id=int(row["tg_id"]),
            referrals=int(row["referrals"] or 0),
            available=Decimal(row["available"] or 0),
            hold=Decimal(row["hold"] or 0),
        )
        for row in rows
    ]

    return stats, total, current_page


def _support_button() -> InlineKeyboardButton | None:
    if not settings.SUPPORT_USERNAME:
        return None
    return InlineKeyboardButton(text=texts.BTN_SUPPORT, url=f"https://t.me/{settings.SUPPORT_USERNAME}")


async def _build_home_text(session: AsyncSession, tg_id: int) -> tuple[str, InlineKeyboardBuilder]:
    snapshot = await db.get_account(session, tg_id)
    account = snapshot.account
    balance = snapshot.balance
    stats = await db.get_stats(session, tg_id)
    link = await db.get_ref_link(tg_id, account)
    available = Decimal(balance.available_amount or 0)
    hold = Decimal(balance.hold_amount or 0)
    method = settings.PAYOUT_METHODS.get(account.payout_method, "не задан") if account.payout_method else "не задан"
    masked = texts.mask_card_number(account.card_last4 or "") if account.card_last4 else "—"

    lines = [texts.TITLE, "", texts.INSTRUCTION, "", texts.LINK_TITLE.format(link=link)]
    lines.append("")
    lines.append(texts.format_stats(stats.get("invited", 0), available, hold, method, masked))
    levels = [(lvl, pct) for lvl, pct in settings.LEVEL_PCTS.items()]
    lines.append("")
    lines.append(texts.format_levels(levels))

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=texts.BTN_WITHDRAW, callback_data="affiliate:payout"))
    builder.row(InlineKeyboardButton(text=texts.BTN_INVITE, callback_data="affiliate:invite"))
    builder.row(InlineKeyboardButton(text=texts.BTN_REQUISITES, callback_data="affiliate:requisites"))
    builder.row(InlineKeyboardButton(text=texts.BTN_BACK, callback_data="affiliate:back"))
    return "\n".join(lines), builder


async def _show_home(message: Message, session: AsyncSession) -> None:
    text, keyboard = await _build_home_text(session, message.chat.id)
    await edit_or_send_message(
        target_message=message,
        text=text,
        reply_markup=keyboard.as_markup(),
        disable_web_page_preview=True,
        force_text=True,
    )


@router.callback_query(F.data == "affiliate:home")
async def open_affiliate(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    await callback.answer()
    await _show_home(callback.message, session)


@router.callback_query(F.data == "affiliate:back")
async def back_to_profile(callback: CallbackQuery, session: AsyncSession, state: FSMContext, admin: bool):
    await state.clear()
    await process_callback_view_profile(callback.message, state, admin, session)


@router.callback_query(F.data == "affiliate:invite")
async def send_invite(callback: CallbackQuery, session: AsyncSession):
    await callback.answer()
    snapshot = await db.get_account(session, callback.from_user.id)
    link = await db.get_ref_link(callback.from_user.id, snapshot.account)
    text = texts.INVITE_MESSAGE.format(link=link)
    display_text = f"{text}\n\n{texts.INVITE_QR_HINT}"
    await edit_or_send_message(
        target_message=callback.message,
        text=display_text,
        reply_markup=None,
        disable_web_page_preview=True,
        force_text=True,
    )
    try:
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(link)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        qr_file = BufferedInputFile(buffer.getvalue(), filename="affiliate_referral.png")
    except Exception as exc:  # noqa: BLE001
        logger.error("[Affiliate] Не удалось создать QR-код ссылки: %s", exc)
        return
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=texts.BTN_CARD_BACK, callback_data="affiliate:home"))
    await callback.message.answer_photo(
        photo=qr_file,
        caption=texts.INVITE_QR_CAPTION.format(link=link),
        reply_markup=builder.as_markup(),
    )


async def _render_requisites(callback: CallbackQuery, session: AsyncSession) -> None:
    snapshot = await db.get_account(session, callback.from_user.id)
    account = snapshot.account
    builder = InlineKeyboardBuilder()
    lines = [texts.CARD_HEADER_EMPTY]
    if not account.payout_method:
        lines.append(texts.CARD_METHOD_NOT_SET)
        lines.append(texts.CARD_PROMPT_SET)
        builder.row(InlineKeyboardButton(text=texts.BTN_ATTACH_CARD, callback_data="affiliate:card:add"))
    else:
        lines.append(texts.CARD_METHOD_SET)
        masked = texts.mask_card_number(account.card_last4 or "")
        lines.append(texts.CARD_CURRENT.format(masked=masked))
        lines.append(texts.CARD_PROMPT_EDIT)
        builder.row(InlineKeyboardButton(text=texts.BTN_EDIT_CARD, callback_data="affiliate:card:edit"))
        builder.row(InlineKeyboardButton(text=texts.BTN_DELETE_CARD, callback_data="affiliate:card:delete"))
    builder.row(InlineKeyboardButton(text=texts.BTN_CARD_BACK, callback_data="affiliate:home"))
    await edit_or_send_message(
        callback.message,
        "\n".join(lines),
        reply_markup=builder.as_markup(),
        disable_web_page_preview=True,
        force_text=True,
    )


@router.callback_query(F.data == "affiliate:requisites")
async def show_requisites(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    await callback.answer()
    await _render_requisites(callback, session)


async def _ensure_user_record(session: AsyncSession, user_data: dict) -> bool:
    tg_id = user_data.get("tg_id")
    if not tg_id:
        return False
    try:
        exists = await check_user_exists(session, tg_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("[Affiliate] Ошибка проверки пользователя перед привязкой: %s", exc)
        return False
    if exists:
        return True
    payload = {
        "tg_id": tg_id,
        "username": user_data.get("username"),
        "first_name": user_data.get("first_name"),
        "last_name": user_data.get("last_name"),
        "language_code": user_data.get("language_code"),
        "is_bot": user_data.get("is_bot", False),
        "source_code": user_data.get("source_code"),
    }
    try:
        await add_user(session=session, **payload)
    except Exception as exc:  # noqa: BLE001
        logger.error("[Affiliate] Ошибка создания пользователя перед привязкой: %s", exc)
        return False
    return True


async def _prompt_card_number(message: Message) -> None:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=texts.BTN_CANCEL, callback_data="affiliate:requisites"))
    await edit_or_send_message(
        target_message=message,
        text=texts.CARD_PROMPT_ENTER,
        reply_markup=builder.as_markup(),
        disable_web_page_preview=True,
        force_text=True,
    )


@router.callback_query(F.data.in_({"affiliate:card:add", "affiliate:card:edit"}))
async def add_or_edit_card(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    await callback.answer()
    await state.set_state(AffiliateStates.wait_card_number)
    await state.update_data(affiliate_card_action=callback.data)
    await _prompt_card_number(callback.message)


@router.message(AffiliateStates.wait_card_number)
async def receive_card_number(message: Message, state: FSMContext, session: AsyncSession):
    raw = message.text.strip()
    # --- Обработка команд и быстрых выходов из состояния ввода карты ---
    # /start — возвращаем пользователя в дом экран партнёрки
    if raw.startswith("/start"):
        await state.clear()
        await _show_home(message, session)
        return
    # "назад"/"отмена"/"cancel" — выводим кнопки для быстрого возврата
    if raw.lower() in {"назад", "отмена", "cancel"}:
        await state.clear()
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text=texts.BTN_CARD_BACK, callback_data="affiliate:home"))
        kb.row(InlineKeyboardButton(text=texts.BTN_REQUISITES, callback_data="affiliate:requisites"))
        await edit_or_send_message(
            target_message=message,
            text=texts.CARD_PROMPT_ENTER,  # нейтральный текст-подсказка
            reply_markup=kb.as_markup(),
            disable_web_page_preview=True,
            force_text=True,
        )
        return

    valid, error = db.validate_card_detailed(raw)
    if not valid:
        # Показываем ошибку + даём кнопки "Назад"
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text="🔙 Назад", callback_data="affiliate:requisites"))
        kb.row(InlineKeyboardButton(text=texts.BTN_CARD_BACK, callback_data="affiliate:home"))
        await message.answer(error or texts.CARD_INVALID, reply_markup=kb.as_markup())
        return
    normalized = "".join(ch for ch in raw if ch.isdigit())
    masked = texts.mask_card_number(normalized)
    await state.update_data(affiliate_card_number=normalized, affiliate_card_mask=masked)
    await state.set_state(AffiliateStates.wait_card_confirm)
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=texts.BTN_SAVE_CARD, callback_data="affiliate:card:confirm"))
    builder.row(InlineKeyboardButton(text=texts.BTN_CANCEL, callback_data="affiliate:requisites"))
    await message.answer(texts.CARD_SAVE_PROMPT.format(masked=masked), reply_markup=builder.as_markup())


@router.callback_query(F.data == "affiliate:card:confirm")
async def confirm_card(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    data = await state.get_data()
    number = data.get("affiliate_card_number")
    if not number:
        await callback.answer(texts.CARD_SAVE_CANCELLED, show_alert=True)
        await state.clear()
        return
    try:
        await db.update_card(session, tg_id=callback.from_user.id, card_number=number, actor=callback.from_user.id)
        await session.commit()
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        logger.error("[Affiliate] Ошибка при сохранении карты: %s", exc, exc_info=True)
        await callback.answer(texts.CARD_INVALID, show_alert=True)
        return
    await state.clear()
    await callback.answer(texts.CARD_SAVED, show_alert=True)
    await _render_requisites(callback, session)


@router.callback_query(F.data == "affiliate:card:delete")
async def delete_card_prompt(callback: CallbackQuery):
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✅ Да", callback_data="affiliate:card:delete:yes"))
    builder.row(InlineKeyboardButton(text=texts.BTN_CANCEL, callback_data="affiliate:requisites"))
    await edit_or_send_message(
        callback.message,
        texts.CARD_DELETE_CONFIRMATION,
        reply_markup=builder.as_markup(),
        disable_web_page_preview=True,
        force_text=True,
    )


@router.callback_query(F.data == "affiliate:card:delete:yes")
async def delete_card(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    await callback.answer()
    try:
        await db.remove_card(session, tg_id=callback.from_user.id, actor=callback.from_user.id)
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        logger.error("[Affiliate] Ошибка при удалении карты: %s", exc, exc_info=True)
        await callback.answer(texts.CARD_DELETE_CANCELLED, show_alert=True)
        return
    await state.clear()
    await callback.answer(texts.CARD_DELETED, show_alert=True)
    await _render_requisites(callback, session)


@router.callback_query(F.data == "affiliate:payout")
async def start_withdraw(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    await callback.answer()
    snapshot = await db.get_account(session, callback.from_user.id)
    account = snapshot.account
    balance = snapshot.balance
    available = Decimal(balance.available_amount or 0)
    builder = InlineKeyboardBuilder()
    if not account.card_last4:
        builder.row(InlineKeyboardButton(text=texts.BTN_REQUISITES, callback_data="affiliate:requisites"))
        builder.row(InlineKeyboardButton(text=texts.BTN_CARD_BACK, callback_data="affiliate:home"))
        await edit_or_send_message(
            callback.message,
            f"{texts.WITHDRAW_HEADER}\n\n{texts.WITHDRAW_NO_CARD}",
            reply_markup=builder.as_markup(),
            disable_web_page_preview=True,
            force_text=True,
        )
        return
    if available < settings.MIN_PAYOUT_RUB:
        builder.row(InlineKeyboardButton(text=texts.BTN_CARD_BACK, callback_data="affiliate:home"))
        await edit_or_send_message(
            callback.message,
            "\n".join(
                [
                    texts.WITHDRAW_HEADER,
                    texts.WITHDRAW_BALANCE.format(available=available, currency=settings.CURRENCY),
                    texts.WITHDRAW_THRESHOLD.format(threshold=settings.MIN_PAYOUT_RUB, currency=settings.CURRENCY),
                    texts.WITHDRAW_INSUFFICIENT.format(available=available, currency=settings.CURRENCY),
                ]
            ),
            reply_markup=builder.as_markup(),
            disable_web_page_preview=True,
            force_text=True,
        )
        return
    pending = await db.get_pending_withdrawal(session, callback.from_user.id)
    if pending:
        builder.row(InlineKeyboardButton(text=texts.BTN_CARD_BACK, callback_data="affiliate:home"))
        await edit_or_send_message(
            callback.message,
            f"{texts.WITHDRAW_HEADER}\n\n{texts.WITHDRAW_PENDING_EXISTS}",
            reply_markup=builder.as_markup(),
            disable_web_page_preview=True,
            force_text=True,
        )
        return
    if not await db.check_withdraw_rate_limit(session, callback.from_user.id):
        builder.row(InlineKeyboardButton(text=texts.BTN_CARD_BACK, callback_data="affiliate:home"))
        await edit_or_send_message(
            callback.message,
            texts.WITHDRAW_RATE_LIMIT,
            reply_markup=builder.as_markup(),
            disable_web_page_preview=True,
            force_text=True,
        )
        return

    await state.set_state(AffiliateStates.wait_withdraw_amount)
    await state.update_data(
        affiliate_withdraw_available=str(available),
    )
    builder.row(InlineKeyboardButton(text=texts.BTN_WITHDRAW_ALL, callback_data="affiliate:withdraw:all"))
    builder.row(InlineKeyboardButton(text=texts.BTN_CANCEL, callback_data="affiliate:home"))
    await edit_or_send_message(
        callback.message,
        "\n".join(
            [
                texts.WITHDRAW_HEADER,
                texts.WITHDRAW_BALANCE.format(available=available, currency=settings.CURRENCY),
                texts.WITHDRAW_THRESHOLD.format(threshold=settings.MIN_PAYOUT_RUB, currency=settings.CURRENCY),
                texts.WITHDRAW_PROMPT_AMOUNT.format(currency=settings.CURRENCY),
            ]
        ),
        reply_markup=builder.as_markup(),
        disable_web_page_preview=True,
        force_text=True,
    )


def _parse_amount(text: str) -> Decimal | None:
    cleaned = text.replace(" ", "").replace(",", ".")
    try:
        value = Decimal(cleaned)
    except Exception:  # noqa: BLE001
        return None
    if value <= 0:
        return None
    return value.quantize(Decimal("0.01"))


@router.message(AffiliateStates.wait_withdraw_amount)
async def receive_withdraw_amount(message: Message, state: FSMContext):
    amount = _parse_amount(message.text.strip())
    if amount is None:
        await message.answer(texts.WITHDRAW_PROMPT_AMOUNT.format(currency=settings.CURRENCY))
        return
    data = await state.get_data()
    available = Decimal(data.get("affiliate_withdraw_available", "0"))
    if amount > available:
        await message.answer(texts.WITHDRAW_INSUFFICIENT.format(available=available, currency=settings.CURRENCY))
        return
    if amount < settings.MIN_PAYOUT_RUB:
        await message.answer(texts.WITHDRAW_THRESHOLD.format(threshold=settings.MIN_PAYOUT_RUB, currency=settings.CURRENCY))
        return
    await state.update_data(affiliate_withdraw_amount=str(amount))
    await state.set_state(AffiliateStates.wait_withdraw_confirm)
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=texts.BTN_WITHDRAW_SEND, callback_data="affiliate:withdraw:confirm"))
    builder.row(InlineKeyboardButton(text=texts.BTN_CANCEL, callback_data="affiliate:home"))
    await message.answer(texts.WITHDRAW_CONFIRM.format(amount=amount, currency=settings.CURRENCY), reply_markup=builder.as_markup())


@router.callback_query(F.data == "affiliate:withdraw:all")
async def withdraw_all(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    available = Decimal(data.get("affiliate_withdraw_available", "0"))
    await state.update_data(affiliate_withdraw_amount=str(available))
    await state.set_state(AffiliateStates.wait_withdraw_confirm)
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=texts.BTN_WITHDRAW_SEND, callback_data="affiliate:withdraw:confirm"))
    builder.row(InlineKeyboardButton(text=texts.BTN_CANCEL, callback_data="affiliate:home"))
    await edit_or_send_message(
        callback.message,
        texts.WITHDRAW_CONFIRM.format(amount=available, currency=settings.CURRENCY),
        reply_markup=builder.as_markup(),
        disable_web_page_preview=True,
        force_text=True,
    )


async def _notify_admins_about_withdrawal(
    callback: CallbackQuery,
    withdrawal_id: int,
    amount: Decimal,
    card_encrypted: bytes | memoryview | None,
    card_mask: str,
    balance_available: Decimal,
    balance_hold: Decimal,
) -> None:
    chat_ids: list[int] = []
    admin_chat = settings.ADMIN_CHAT_ID
    if isinstance(admin_chat, (list, tuple)):
        chat_ids.extend(int(chat) for chat in admin_chat)
    elif isinstance(admin_chat, int):
        chat_ids.append(admin_chat)
    if not chat_ids:
        return
    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        InlineKeyboardButton(
            text="✅ Оплата проведена",
            callback_data=f"admin:affiliate:withdraw:paid|{withdrawal_id}",
        ),
        InlineKeyboardButton(
            text="❌ Не проведена",
            callback_data=f"admin:affiliate:withdraw:reject|{withdrawal_id}",
        ),
    )
    keyboard.row(InlineKeyboardButton(text="👤 Открыть пользователя", url=f"tg://user?id={callback.from_user.id}"))
    markup = keyboard.as_markup()
    for chat_id in chat_ids:
        card_number = card_mask
        if card_encrypted:
            try:
                card_number = db.decrypt_card(bytes(card_encrypted))
            except Exception as exc:  # noqa: BLE001
                logger.error("[Affiliate] Не удалось расшифровать карту для уведомления: %s", exc, exc_info=True)
        text = texts.ADMIN_WITHDRAW_NOTIFICATION.format(
            id=withdrawal_id,
            tg_id=callback.from_user.id,
            username=callback.from_user.username or callback.from_user.full_name,
            amount=amount,
            currency=settings.CURRENCY,
            available=balance_available,
            hold=balance_hold,
            card_mask=card_mask,
            card_number=card_number,
            created=texts.format_datetime(datetime.utcnow()),
        )
        try:
            await callback.bot.send_message(chat_id, text, reply_markup=markup)
        except Exception as exc:  # noqa: BLE001
            logger.error("[Affiliate] Не удалось отправить уведомление админу %s: %s", chat_id, exc)


@router.callback_query(F.data == "affiliate:withdraw:confirm")
async def confirm_withdraw(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    data = await state.get_data()
    amount = Decimal(data.get("affiliate_withdraw_amount", "0"))
    if amount <= 0:
        await callback.answer(texts.WITHDRAW_PROMPT_AMOUNT.format(currency=settings.CURRENCY), show_alert=True)
        return
    snapshot = await db.get_account(session, callback.from_user.id)
    card_mask = texts.mask_card_number(snapshot.account.card_last4 or "")
    try:
        withdrawal = await db.create_withdrawal(
            session,
            tg_id=callback.from_user.id,
            amount=amount,
            method=settings.PAYOUT_METHOD_CARD_RU,
            card_snapshot=card_mask,
            actor=callback.from_user.id,
        )
        await session.commit()
    except ValueError:
        await session.rollback()
        current_available = Decimal(snapshot.balance.available_amount or 0)
        await callback.answer(
            texts.WITHDRAW_INSUFFICIENT.format(available=current_available, currency=settings.CURRENCY),
            show_alert=True,
        )
        return
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        logger.error("[Affiliate] Ошибка при создании заявки: %s", exc, exc_info=True)
        await callback.answer("Не удалось создать заявку", show_alert=True)
        return
    await state.clear()
    builder = InlineKeyboardBuilder()
    support_btn = _support_button()
    if support_btn:
        builder.row(support_btn)
    builder.row(InlineKeyboardButton(text=texts.BTN_CARD_BACK, callback_data="affiliate:home"))
    await edit_or_send_message(
        callback.message,
        texts.WITHDRAW_CREATED.format(withdraw_id=withdrawal.id, amount=amount, currency=settings.CURRENCY),
        reply_markup=builder.as_markup(),
        disable_web_page_preview=True,
        force_text=True,
    )
    await callback.answer()
    await _notify_admins_about_withdrawal(
        callback,
        withdrawal.id,
        amount,
        snapshot.account.card_encrypted,
        card_mask,
        Decimal(snapshot.balance.available_amount or 0),
        Decimal(snapshot.balance.hold_amount or 0),
    )


async def _admin_check(callback: CallbackQuery) -> bool:
    if callback.message.chat.type not in {ChatType.PRIVATE, ChatType.SUPERGROUP, ChatType.GROUP}:
        return False
    if settings.ADMIN_IDS:
        return callback.from_user.id in settings.ADMIN_IDS
    return True


def _parse_admin_callback(data: str) -> tuple[str, int, int, str]:
    parts = data.split("|", 4)
    parts += [""] * (5 - len(parts))
    _, status, page, period, tg_part = parts
    status = status or "pending"
    page_val = int(page or 1)
    period_val = int(period or 30)
    tg_filter = tg_part.strip().strip("|") or "-"
    return status, max(1, page_val), max(1, period_val), tg_filter


async def _render_admin_list(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    *,
    status: str,
    page: int,
    period: int,
    tg_filter: str,
) -> None:
    tg_id: int | None = None
    if tg_filter not in {"-", ""}:
        try:
            tg_id = int(tg_filter)
        except ValueError:
            tg_id = None
    since = datetime.utcnow() - timedelta(days=period) if period else None
    withdrawals, total = await db.list_withdrawals(
        session,
        status=status if status != "all" else None,
        since=since,
        tg_id=tg_id,
        page=page,
        page_size=settings.DEFAULT_PAGE_SIZE,
    )
    total_pages = max(1, (total + settings.DEFAULT_PAGE_SIZE - 1) // settings.DEFAULT_PAGE_SIZE)
    balances = await db.get_balance_map(session, [w.tg_id for w in withdrawals])
    lines = [texts.ADMIN_WITHDRAW_TITLE, ""]
    if not withdrawals:
        lines.append(texts.ADMIN_WITHDRAW_EMPTY)
    else:
        for withdraw in withdrawals:
            balance = balances.get(withdraw.tg_id)
            available = Decimal(balance.available_amount or 0) if balance else Decimal("0")
            hold = Decimal(balance.hold_amount or 0) if balance else Decimal("0")
            lines.append(
                texts.ADMIN_WITHDRAW_LINE.format(
                    id=withdraw.id,
                    status=texts.STATUS_TITLES.get(withdraw.status, withdraw.status),
                    tg_id=withdraw.tg_id,
                    amount=Decimal(withdraw.amount or 0),
                    currency=settings.CURRENCY,
                    created=texts.format_datetime(withdraw.created_at),
                    method=settings.PAYOUT_METHODS.get(withdraw.method, withdraw.method),
                    card_line=texts.ADMIN_WITHDRAW_CARD.format(masked=withdraw.card_snapshot_masked),
                    available=available,
                    hold=hold,
                    admin=withdraw.admin_id or "—",
                )
            )
    text = "\n".join(lines)

    builder = InlineKeyboardBuilder()
    status_buttons = []
    for status_key in ("pending", "paid", "rejected", "all"):
        label = texts.STATUS_TITLES.get(status_key, status_key.title())
        if status_key == status:
            label = f"• {label}"
        status_buttons.append(
            InlineKeyboardButton(
                text=label,
                callback_data=f"affiliate:admin:list|{status_key}|1|{period}|{tg_filter}",
            )
        )
    builder.row(*status_buttons[:2])
    builder.row(*status_buttons[2:])

    period_buttons = []
    for period_option in (7, 30, 90):
        label = f"{period_option}д"
        if period_option == period:
            label = f"• {label}"
        period_buttons.append(
            InlineKeyboardButton(
                text=label,
                callback_data=f"affiliate:admin:list|{status}|1|{period_option}|{tg_filter}",
            )
        )
    builder.row(*period_buttons[:2])
    if len(period_buttons) > 2:
        builder.row(period_buttons[2])

    tg_label = texts.BTN_ADMIN_FILTER_TG
    if tg_id:
        tg_label += f" ({tg_id})"
    builder.row(InlineKeyboardButton(text=tg_label, callback_data="affiliate:admin:tg"))
    builder.row(InlineKeyboardButton(text=texts.BTN_ADMIN_CLEAR_FILTERS, callback_data="affiliate:admin:list|pending|1|30|-") )

    nav_row: list[InlineKeyboardButton] = []
    if page > 1:
        nav_row.append(
            InlineKeyboardButton(
                text="◀️",
                callback_data=f"affiliate:admin:list|{status}|{page - 1}|{period}|{tg_filter}",
            )
        )
    nav_row.append(
        InlineKeyboardButton(
            text=f"{page}/{total_pages}",
            callback_data=f"affiliate:admin:list|{status}|{page}|{period}|{tg_filter}",
        )
    )
    if page < total_pages:
        nav_row.append(
            InlineKeyboardButton(
                text="▶️",
                callback_data=f"affiliate:admin:list|{status}|{page + 1}|{period}|{tg_filter}",
            )
        )
    builder.row(*nav_row)
    builder.row(InlineKeyboardButton(text=texts.BTN_ADMIN_BACK, callback_data=AdminPanelCallback(action="admin").pack()))

    await state.update_data(
        affiliate_admin_filters={
            "status": status,
            "page": page,
            "period": period,
            "tg": tg_filter,
        }
    )
    await edit_or_send_message(
        message,
        text,
        reply_markup=builder.as_markup(),
        disable_web_page_preview=True,
        force_text=True,
    )


@router.callback_query(F.data.startswith("affiliate:admin:list"))
async def admin_list(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    if not await _admin_check(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer()
    status, page, period, tg_filter = _parse_admin_callback(callback.data)
    await _render_admin_list(callback.message, session, state, status=status, page=page, period=period, tg_filter=tg_filter)


async def _render_admin_stats(message: Message, session: AsyncSession, *, page: int) -> None:
    page_size = settings.DEFAULT_PAGE_SIZE
    stats, total, current_page = await _fetch_partner_stats(
        session,
        page=page,
        page_size=page_size,
    )
    total_pages = max(1, (total + page_size - 1) // page_size) if total else 1
    page_number = current_page if total else 1

    lines = [texts.ADMIN_PARTNER_STATS_TITLE, ""]
    if not stats:
        lines.append(texts.ADMIN_PARTNER_STATS_EMPTY)
    else:
        for item in stats:
            total_balance = item.available + item.hold
            lines.append(
                texts.ADMIN_PARTNER_STATS_LINE.format(
                    tg_id=item.tg_id,
                    referrals=item.referrals,
                    total=total_balance,
                    available=item.available,
                    hold=item.hold,
                    currency=settings.CURRENCY,
                )
            )

    text = "\n".join(lines)
    builder = InlineKeyboardBuilder()

    nav_row: list[InlineKeyboardButton] = []
    if page_number > 1:
        nav_row.append(
            InlineKeyboardButton(
                text="◀️",
                callback_data=f"affiliate:admin:stats|{page_number - 1}",
            )
        )
    nav_row.append(
        InlineKeyboardButton(
            text=f"{page_number}/{total_pages}",
            callback_data=f"affiliate:admin:stats|{page_number}",
        )
    )
    if total and page_number < total_pages:
        nav_row.append(
            InlineKeyboardButton(
                text="▶️",
                callback_data=f"affiliate:admin:stats|{page_number + 1}",
            )
        )
    builder.row(*nav_row)
    builder.row(InlineKeyboardButton(text=texts.BTN_ADMIN_BACK, callback_data=AdminPanelCallback(action="admin").pack()))

    await edit_or_send_message(
        message,
        text,
        reply_markup=builder.as_markup(),
        disable_web_page_preview=True,
        force_text=True,
    )


@router.callback_query(F.data.startswith("affiliate:admin:stats"))
async def admin_partner_stats(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    if not await _admin_check(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    await callback.answer()
    parts = callback.data.split("|", 1)
    page = 1
    if len(parts) > 1 and parts[1]:
        try:
            page = max(1, int(parts[1]))
        except ValueError:
            page = 1
    await _render_admin_stats(callback.message, session, page=page)


@router.callback_query(F.data == "affiliate:admin:tg")
async def admin_filter_tg(callback: CallbackQuery, state: FSMContext):
    await callback.answer("Введите tg_id пользователя", show_alert=True)
    await state.set_state(AffiliateStates.wait_admin_tg_id)


@router.message(AffiliateStates.wait_admin_tg_id)
async def admin_receive_tg(message: Message, session: AsyncSession, state: FSMContext):
    data = await state.get_data()
    filters = data.get(
        "affiliate_admin_filters",
        {"status": "pending", "page": 1, "period": 30, "tg": "-"},
    )
    text = message.text.strip()
    if text.lower() in {"отмена", "cancel"}:
        tg_filter = "-"
    else:
        try:
            tg_filter = str(int(text))
        except ValueError:
            await message.answer("Введите числовой tg_id или 'отмена'.")
            return
    await state.clear()
    await _render_admin_list(
        message,
        session,
        state,
        status=filters.get("status", "pending"),
        page=1,
        period=int(filters.get("period", 30)),
        tg_filter=tg_filter,
    )


async def _handle_admin_decision(
    callback: CallbackQuery,
    session: AsyncSession,
    *,
    withdrawal_id: int,
    status: str,
) -> None:
    if not await _admin_check(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return
    try:
        withdrawal = await db.set_withdrawal_status(
            session,
            withdrawal_id=withdrawal_id,
            status=status,
            admin_id=callback.from_user.id,
        )
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        logger.error("[Affiliate] Ошибка при обновлении заявки: %s", exc, exc_info=True)
        await callback.answer("Ошибка", show_alert=True)
        return
    if not withdrawal:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    if withdrawal.status != status:
        await callback.answer(texts.ADMIN_WITHDRAW_ALREADY_PROCESSED, show_alert=True)
        return
    user_keyboard = InlineKeyboardBuilder()
    support_btn = _support_button()
    if support_btn:
        user_keyboard.row(support_btn)
    user_keyboard.row(InlineKeyboardButton(text=texts.BTN_CARD_BACK, callback_data="affiliate:home"))
    try:
        if status == "paid":
            await callback.bot.send_message(
                withdrawal.tg_id,
                texts.WITHDRAW_USER_SUCCESS.format(
                    withdraw_id=withdrawal.id,
                    amount=Decimal(withdrawal.amount or 0),
                    currency=settings.CURRENCY,
                ),
                reply_markup=user_keyboard.as_markup(),
            )
            await callback.answer(texts.ADMIN_WITHDRAW_APPROVED.format(id=withdrawal.id), show_alert=True)
        else:
            await callback.bot.send_message(
                withdrawal.tg_id,
                texts.WITHDRAW_USER_REJECT.format(
                    withdraw_id=withdrawal.id,
                    amount=Decimal(withdrawal.amount or 0),
                    currency=settings.CURRENCY,
                ),
                reply_markup=user_keyboard.as_markup(),
            )
            await callback.answer(texts.ADMIN_WITHDRAW_REJECTED.format(id=withdrawal.id), show_alert=True)
    except Exception as exc:  # noqa: BLE001
        logger.error("[Affiliate] Ошибка отправки уведомления пользователю: %s", exc)
        await callback.answer("Готово", show_alert=True)


@router.callback_query(F.data.startswith("admin:affiliate:withdraw:paid|"))
async def admin_mark_paid(callback: CallbackQuery, session: AsyncSession):
    withdrawal_id = int(callback.data.split("|")[1])
    await _handle_admin_decision(callback, session, withdrawal_id=withdrawal_id, status="paid")


@router.callback_query(F.data.startswith("admin:affiliate:withdraw:reject|"))
async def admin_mark_reject(callback: CallbackQuery, session: AsyncSession):
    withdrawal_id = int(callback.data.split("|")[1])
    await _handle_admin_decision(callback, session, withdrawal_id=withdrawal_id, status="rejected")


async def start_link_hook(message: Message, state: FSMContext, session: AsyncSession, user_data: dict, part: str, **_: Any):
    if not part.startswith("affiliate_"):
        return
    code = part.split("_", 1)[1]
    account = await db.get_account_by_code(session, code)
    if not account:
        logger.warning("[Affiliate] Неизвестный партнёрский код: %s", code)
        return
    user_id = user_data.get("tg_id")
    if not user_id or user_id == account.tg_id:
        return
    if not await _ensure_user_record(session, user_data):
        return
    existing = await get_referral_by_referred_id(session, user_id)
    if existing:
        return
    try:
        await add_referral(session, referred_tg_id=user_id, referrer_tg_id=account.tg_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("[Affiliate] Ошибка привязки реферала: %s", exc)
        return
    await db.refresh_tree(session, user_id)
    await session.commit()


async def referral_bound_hook(tg_id: int, session: AsyncSession, **_: Any):
    try:
        await db.refresh_tree(session, tg_id)
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        logger.error("[Affiliate] Ошибка обновления дерева: %s", exc)


async def payment_success_hook(
    session: AsyncSession,
    tg_id: int | None = None,
    amount: float | int | None = None,
    bot: Any | None = None,
    **kwargs: Any,
):
    tg_id = tg_id or kwargs.get("tg_id") or kwargs.get("user_id")
    if tg_id is None:
        logger.warning("[Affiliate] Пропуск начисления: не передан tg_id в payment_success_hook")
        return
    try:
        value = kwargs.get("amount_rub") or amount or kwargs.get("amount") or kwargs.get("paid_amount")
        if value is None:
            return
        base_amount = Decimal(str(value))
        if base_amount <= 0:
            return
        parents = await db.get_parent_chain(session, tg_id)
        hold_until = None
        if settings.HOLD_DAYS > 0:
            hold_until = datetime.utcnow() + timedelta(days=settings.HOLD_DAYS)
        for level, parent in enumerate(parents, start=1):
            if not parent:
                continue
            pct = settings.LEVEL_PCTS.get(level)
            if not pct:
                continue
            reward = (base_amount * pct).quantize(Decimal("0.01"))
            if reward <= 0:
                continue
            await db.accrue_reward(
                session,
                tg_id=parent,
                amount=reward,
                level=level,
                payment_id=str(kwargs.get("payment_id") or ""),
                ref_order_id=str(kwargs.get("order_id") or kwargs.get("invoice_id") or ""),
                hold_until=hold_until,
                comment=f"referral:{tg_id}",
            )
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        logger.error("[Affiliate] Ошибка начисления вознаграждения: %s", exc, exc_info=True)


async def periodic_notifications_hook(bot: Any, session: AsyncSession, **_: Any):
    try:
        released = await db.release_accruals(session)
        if released:
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        logger.error("[Affiliate] Ошибка релиза начислений: %s", exc)
    balances: list[AffiliateBalance] = []
    try:
        result = await session.execute(
            select(AffiliateBalance).where(AffiliateBalance.available_amount >= settings.MIN_PAYOUT_RUB)
        )
        balances = result.scalars().all()
    except Exception as exc:  # noqa: BLE001
        logger.error("[Affiliate] Ошибка выборки балансов: %s", exc)
    for balance in balances:
        can_notify = await db.can_notify(
            session,
            tg_id=balance.tg_id,
            action="user_threshold",
            period=settings.USER_REMINDER_PERIOD,
        )
        if not can_notify:
            continue
        try:
            await bot.send_message(
                balance.tg_id,
                texts.USER_THRESHOLD_REMINDER.format(
                    amount=Decimal(balance.available_amount or 0),
                    currency=settings.CURRENCY,
                ),
            )
            await db.mark_notification(session, tg_id=balance.tg_id, action="user_threshold")
        except Exception as exc:  # noqa: BLE001
            logger.error("[Affiliate] Ошибка уведомления пользователя: %s", exc)
    try:
        pending = await db.get_pending_for_admin_reminder(session, older_than=settings.ADMIN_PENDING_REMINDER)
        if pending:
            chat_ids: list[int] = []
            admin_chat = settings.ADMIN_CHAT_ID
            if isinstance(admin_chat, (list, tuple)):
                chat_ids.extend(int(chat) for chat in admin_chat)
            elif isinstance(admin_chat, int):
                chat_ids.append(admin_chat)
            if chat_ids:
                oldest = pending[0]
                for chat_id in chat_ids:
                    can_notify = await db.can_notify(
                        session,
                        tg_id=chat_id,
                        action="admin_pending",
                        period=settings.ADMIN_PENDING_REMINDER,
                    )
                    if not can_notify:
                        continue
                    try:
                        await bot.send_message(
                            chat_id,
                            texts.ADMIN_PENDING_REMINDER.format(
                                count=len(pending),
                                id=oldest.id,
                                tg_id=oldest.tg_id,
                                currency=settings.CURRENCY,
                                amount=Decimal(oldest.amount or 0),
                            ),
                        )
                        await db.mark_notification(session, tg_id=chat_id, action="admin_pending")
                    except Exception as exc:  # noqa: BLE001
                        logger.error("[Affiliate] Ошибка уведомления админа: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.error("[Affiliate] Ошибка напоминаний админам: %s", exc)
    await session.commit()


async def start_menu_hook(**_: Any):
    if not settings.ENABLE_BUTTON:
        return None
    return {"button": InlineKeyboardButton(text="💰 Заработать с VlessWB", callback_data="affiliate:home")}


async def profile_menu_hook(**_: Any):
    if not settings.ENABLE_BUTTON:
        return None
    return {"button": InlineKeyboardButton(text="💰 Партнерская программа", callback_data="affiliate:home")}


async def admin_panel_hook(admin_role: str, **_: Any):
    if admin_role not in {"admin", "superadmin"}:
        return None
    return [
        {
            "button": InlineKeyboardButton(
                text="🧾 Выплаты партнёрам",
                callback_data="affiliate:admin:list|pending|1|30|-",
            )
        },
        {
            "button": InlineKeyboardButton(
                text="📈 Статистика по партнёрам",
                callback_data="affiliate:admin:stats|1",
            )
        },
    ]


register_hook("start_link", start_link_hook)
register_hook("referral_bound", referral_bound_hook)
register_hook("payment_success", payment_success_hook)
register_hook("periodic_notifications", periodic_notifications_hook)
register_hook("start_menu", start_menu_hook)
register_hook("profile_menu", profile_menu_hook)
register_hook("admin_panel", admin_panel_hook)
