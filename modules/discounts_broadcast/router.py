from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_tariffs
from handlers.notifications.notify_kb import build_tariffs_keyboard
from hooks.hooks import register_hook
from logger import logger

from . import services, settings, texts
from .services import ADMIN_IDS

router = Router(name="discounts_broadcast")


async def periodic_notifications_hook(bot, session: AsyncSession, **_: Any):
    try:
        await services.process_periodic(bot=bot, session=session)
    except Exception as exc:
        logger.error(f"[DiscountsBroadcast] Ошибка периодической рассылки: {exc}")


register_hook("periodic_notifications", periodic_notifications_hook)


async def admin_panel_hook(**kwargs: Any):
    admin_role = kwargs.get("admin_role")
    if settings.TEST_BUTTON_VISIBLE_FOR and admin_role not in settings.TEST_BUTTON_VISIBLE_FOR:
        return None
    return [
        {
            "button": InlineKeyboardButton(
                text=texts.ADMIN_PANEL_BUTTON,
                callback_data="discounts_broadcast|test",
            )
        },
        {
            "button": InlineKeyboardButton(
                text=texts.ADMIN_ENABLE_BUTTON,
                callback_data="discounts_broadcast|enable",
            )
        },
    ]


register_hook("admin_panel", admin_panel_hook)


@router.callback_query(F.data == "discounts_broadcast|test")
async def handle_admin_test(callback: CallbackQuery, session: AsyncSession):
    tg_id = callback.from_user.id
    if tg_id not in ADMIN_IDS:
        await callback.answer(texts.ADMIN_TEST_DENIED, show_alert=True)
        return

    try:
        sent = await services.send_admin_test(callback.bot, session=session)
    except Exception as exc:
        logger.error(f"[DiscountsBroadcast] Ошибка тестовой рассылки: {exc}")
        await callback.answer(texts.ADMIN_TEST_FAILED, show_alert=True)
        return

    if sent:
        await callback.answer(texts.ADMIN_TEST_SUCCESS.format(sent=sent), show_alert=True)
    else:
        await callback.answer(texts.ADMIN_TEST_EMPTY, show_alert=True)


@router.callback_query(F.data == "discounts_broadcast|enable")
async def handle_admin_enable(callback: CallbackQuery, session: AsyncSession):
    tg_id = callback.from_user.id
    if tg_id not in ADMIN_IDS:
        await callback.answer(texts.ADMIN_TEST_DENIED, show_alert=True)
        return

    try:
        enabled = await services.enable_broadcast(session)
    except Exception as exc:
        logger.error(f"[DiscountsBroadcast] Ошибка включения авторассылки: {exc}")
        await callback.answer(texts.ADMIN_ENABLE_FAILED, show_alert=True)
        return

    if enabled:
        await callback.answer(texts.ADMIN_ENABLE_SUCCESS, show_alert=True)
    else:
        await callback.answer(texts.ADMIN_ENABLE_ALREADY, show_alert=True)


@router.callback_query(F.data == "discounts_broadcast|open")
async def open_tariffs(callback: CallbackQuery, session: AsyncSession):
    try:
        tariffs = await get_tariffs(session=session, group_code=settings.TARIFF_GROUP)
    except Exception as exc:
        logger.error(f"[DiscountsBroadcast] Не удалось получить тарифы: {exc}")
        await callback.answer(texts.NO_TARIFFS_AVAILABLE, show_alert=True)
        return

    if not tariffs:
        await callback.answer(texts.NO_TARIFFS_AVAILABLE, show_alert=True)
        return

    # Используем основной обработчик выбора тарифа, чтобы исключить эмуляцию
    # колбэка и ошибки "method is not mounted" в key_discount_mode.
    keyboard = build_tariffs_keyboard(tariffs, prefix="select_tariff_plan")
    await callback.message.answer(texts.TARIFFS_PROMPT, reply_markup=keyboard)
    await callback.answer()
