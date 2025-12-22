from __future__ import annotations

from datetime import datetime

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from config import ADMIN_ID
from handlers.notifications.notify_utils import send_messages_with_limit
from logger import logger

from . import db, keyboards, settings, texts

if isinstance(ADMIN_ID, (list, tuple, set)):
    ADMIN_IDS = {int(x) for x in ADMIN_ID if x is not None}
elif ADMIN_ID:
    ADMIN_IDS = {int(ADMIN_ID)}
else:
    ADMIN_IDS = set()


async def _send_messages(
    bot: Bot,
    recipients: list[int],
    keyboard: InlineKeyboardMarkup,
    *,
    session: AsyncSession | None,
) -> int:
    if not recipients:
        return 0

    messages = [
        {"tg_id": tg_id, "text": texts.DISCOUNT_MESSAGE, "keyboard": keyboard}
        for tg_id in recipients
    ]
    results = await send_messages_with_limit(
        bot,
        messages,
        session=session,
        source_file="discounts_broadcast",
    )
    sent = sum(1 for result in results if result)
    logger.info(
        f"[DiscountsBroadcast] Сообщения отправлены: {sent} из {len(recipients)} адресатов",
    )
    return sent


async def process_periodic(bot: Bot, session: AsyncSession, **_: object) -> None:
    state = await db.ensure_state(session)
    if not state.is_enabled:
        logger.debug("[DiscountsBroadcast] Рассылка не активирована администратором — пропуск")
        return

    now = datetime.utcnow()
    last_sent = state.last_sent_at
    if last_sent and now - last_sent < settings.SEND_INTERVAL:
        logger.debug("[DiscountsBroadcast] Интервал ещё не истёк — рассылка пропущена")
        return

    recipients = await db.fetch_target_user_ids(session)
    if not recipients:
        logger.info("[DiscountsBroadcast] Получателей для рассылки нет — обновляю таймер")
        await db.touch_last_sent_at(session, now)
        return

    await db.activate_discount(session, recipients, now)
    keyboard = keyboards.broadcast_keyboard()
    await _send_messages(bot, recipients, keyboard, session=session)
    await db.touch_last_sent_at(session, now)


async def send_admin_test(bot: Bot, session: AsyncSession | None = None) -> int:
    keyboard = keyboards.broadcast_keyboard()
    recipients = sorted(ADMIN_IDS)
    if session and recipients:
        now = datetime.utcnow()
        try:
            await db.activate_discount(session, recipients, now)
        except Exception as exc:
            logger.warning(
                "[DiscountsBroadcast] Не удалось активировать скидку для админов: %s",
                exc,
            )
    sent = await _send_messages(bot, recipients, keyboard, session=session)
    if not recipients:
        logger.warning("[DiscountsBroadcast] ADMIN_ID пуст — тестовая рассылка не отправлена")
    return sent


async def enable_broadcast(session: AsyncSession) -> bool:
    state = await db.ensure_state(session)
    if state.is_enabled:
        return False

    await db.set_enabled(session, True)
    return True
