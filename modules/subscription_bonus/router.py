import logging
import uuid
from datetime import timedelta

from aiogram import F, Bot, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import StorageKey
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .bonus_config import *
from .models import SubscriptionBonus

logger = logging.getLogger(__name__)
router = Router()


class BonusFlowState(StatesGroup):
    awaiting_key_creation = State()


async def register_bonus_button(session: AsyncSession, chat_id: int, **kwargs):
    """
    Создает и возвращает кнопку для меню профиля,
    только если пользователь еще не получал бонус.
    """
    if await has_received_bonus(session, chat_id):
        return None
    return {
        "button": InlineKeyboardButton(text=PROFILE_BUTTON_TEXT, callback_data="sub_bonus_start"),
    }


async def _edit_message_safely(bot: Bot, message: types.Message, text: str, reply_markup=None):
    """
    Универсальная функция, которая редактирует сообщение,
    независимо от того, есть в нем фото или нет.
    """
    try:
        logger.debug(f"User {message.chat.id}: Attempting to edit message {message.message_id}.")
        is_modified = False
        current_text = message.caption if message.photo else message.text

        if current_text != text or message.reply_markup != reply_markup:
            is_modified = True

        logger.debug(f"User {message.chat.id}: Message modification required: {is_modified}.")

        if not is_modified:
            return

        if message.photo:
            await bot.edit_message_caption(
                chat_id=message.chat.id,
                message_id=message.message_id,
                caption=text,
                reply_markup=reply_markup,
            )
        else:
            await bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=message.message_id,
                text=text,
                reply_markup=reply_markup,
            )
        logger.debug(f"User {message.chat.id}: Message {message.message_id} edited successfully.")

    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            logger.warning(f"User {message.chat.id}: Failed to edit message: {e}")
        else:
            logger.debug(f"User {message.chat.id}: Message not modified, Telegram API confirmed.")


async def has_received_bonus(session: AsyncSession, user_id: int) -> bool:
    """Проверяет, получал ли пользователь бонус."""
    result = await session.execute(select(SubscriptionBonus).where(SubscriptionBonus.user_id == user_id))
    return result.scalar_one_or_none() is not None


async def mark_bonus_as_received(session: AsyncSession, user_id: int):
    """Отмечает, что пользователь получил бонус."""
    new_record = SubscriptionBonus(user_id=user_id)
    session.add(new_record)
    await session.commit()


async def send_subscription_prompt(bot: Bot, chat_id: int):
    """Отправляет новое сообщение с предложением подписаться."""
    builder = InlineKeyboardBuilder()
    for channel in REQUIRED_CHANNELS:
        button_text = channel.get("name", f"Канал «{channel['url'].split('/')[-1]}»")
        builder.row(InlineKeyboardButton(text=button_text, url=channel["url"]))

    builder.row(InlineKeyboardButton(text=CHECK_BUTTON_TEXT, callback_data="sub_bonus_check"))
    builder.row(InlineKeyboardButton(text=BACK_BUTTON_TEXT, callback_data="profile"))

    await bot.send_message(
        chat_id=chat_id,
        text=SUBSCRIBE_PROMPT_MESSAGE.format(days=BONUS_DAYS),
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data == "sub_bonus_start")
async def bonus_entry_point(callback: types.CallbackQuery, session: AsyncSession, bot: Bot, state: FSMContext):
    """Главная точка входа в модуль."""
    user_id = callback.from_user.id
    logger.info(f"--- User {user_id}: START bonus_entry_point ---")

    try:
        try:
            await callback.answer()
        except Exception:
            pass

        from database import get_key_count

        already_received = await has_received_bonus(session, user_id)
        logger.info(f"User {user_id}: Check has_received_bonus. Result: {already_received}")

        if already_received:
            logger.info(f"User {user_id}: Exiting because bonus was already received.")
            builder = InlineKeyboardBuilder()
            builder.row(InlineKeyboardButton(text=BACK_BUTTON_TEXT, callback_data="profile"))
            await _edit_message_safely(
                bot,
                callback.message,
                ALREADY_RECEIVED_MESSAGE,
                reply_markup=builder.as_markup(),
            )
            await callback.answer(ALREADY_RECEIVED_MESSAGE, show_alert=True)
            logger.info(f"--- User {user_id}: END bonus_entry_point ---")
            return

        key_count = await get_key_count(session, user_id)
        logger.info(f"User {user_id}: Check get_key_count. Result: {key_count}")

        user_has_key = key_count is not None and key_count > 0

        if user_has_key:
            logger.info(f"User {user_id}: Condition user_has_key is TRUE. Showing subscription prompt.")
            builder = InlineKeyboardBuilder()
            for channel in REQUIRED_CHANNELS:
                button_text = channel.get("name", f"Канал «{channel['url'].split('/')[-1]}»")
                builder.row(InlineKeyboardButton(text=button_text, url=channel["url"]))

            builder.row(InlineKeyboardButton(text=CHECK_BUTTON_TEXT, callback_data="sub_bonus_check"))
            builder.row(InlineKeyboardButton(text=BACK_BUTTON_TEXT, callback_data="profile"))

            await _edit_message_safely(
                bot,
                callback.message,
                SUBSCRIBE_PROMPT_MESSAGE.format(days=BONUS_DAYS),
                reply_markup=builder.as_markup(),
            )
        else:
            logger.info(f"User {user_id}: Condition user_has_key is FALSE. Showing 'no key' message.")
            await state.set_state(BonusFlowState.awaiting_key_creation.state)
            logger.info(f"User {user_id}: Set state to awaiting_key_creation.")

            builder = InlineKeyboardBuilder()
            builder.row(
                InlineKeyboardButton(text=REFRESH_BUTTON_TEXT, callback_data="sub_bonus_start"),
                InlineKeyboardButton(text=BACK_BUTTON_TEXT, callback_data="profile"),
            )

            await _edit_message_safely(bot, callback.message, NO_KEY_MESSAGE, reply_markup=builder.as_markup())

            answer_text = "У вас по-прежнему нет активной подписки. Создайте ее и нажмите 'Обновить'."
            logger.info(f"User {user_id}: Answering callback with alert: '{answer_text}'")
            await callback.answer(answer_text, show_alert=True)

    except Exception as e:
        logger.error(f"User {user_id}: UNCAUGHT EXCEPTION in bonus_entry_point: {e}", exc_info=True)
        await callback.answer("Произошла внутренняя ошибка.", show_alert=True)

    logger.info(f"--- User {user_id}: END bonus_entry_point ---")


async def bonus_after_key_creation(message: types.Message, session: AsyncSession, **kwargs):
    """
    Этот обработчик вызывается хуком 'after_key_created' из ядра бота.
    """
    bot = message.bot
    user_id = message.chat.id
    logger.info(f"--- User {user_id}: HOOK bonus_after_key_creation triggered ---")

    storage_key = StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id)
    state = FSMContext(storage=bot.dispatcher.storage, key=storage_key)

    current_state = await state.get_state()
    logger.info(f"User {user_id}: Current state is {current_state}")

    if current_state == BonusFlowState.awaiting_key_creation.state:
        logger.info(f"User {user_id}: State matches. Sending subscription prompt.")
        await state.clear()
        try:
            await bot.delete_message(chat_id=user_id, message_id=message.message_id)
        except TelegramBadRequest:
            pass
        await send_subscription_prompt(bot, user_id)
    else:
        logger.info(f"User {user_id}: State does not match. Hook is doing nothing.")
    logger.info(f"--- User {user_id}: END bonus_after_key_creation ---")


@router.callback_query(F.data == "sub_bonus_check")
async def check_channel_subscription(callback: types.CallbackQuery, session: AsyncSession, bot: Bot, state: FSMContext):
    """Проверяет подписку и автоматически активирует бонус."""
    from database.coupons import create_coupon
    from handlers.coupons import activate_coupon

    user_id = callback.from_user.id

    if await has_received_bonus(session, user_id):
        await callback.answer(ALREADY_RECEIVED_MESSAGE, show_alert=True)
        return

    await callback.answer("Проверяем подписку...")

    try:
        for channel in REQUIRED_CHANNELS:
            member = await bot.get_chat_member(chat_id=channel["id"], user_id=user_id)
            if member.status not in ["member", "administrator", "creator"]:
                await callback.answer(NOT_SUBSCRIBED_YET_MSG, show_alert=True)
                return
    except Exception as e:
        logger.error(f"[Subscription Bonus] Ошибка проверки подписки для {user_id}: {e}")
        await callback.answer(SUBSCRIPTION_CHECK_ERROR_MSG, show_alert=True)
        return

    coupon_code = f"SUBBONUS{BONUS_DAYS}D-{str(uuid.uuid4())[:8].upper()}"
    success = await create_coupon(
        session=session, code=coupon_code, days=BONUS_DAYS, usage_limit=1, amount=0
    )

    if not success:
        logger.error(f"[Subscription Bonus] Не удалось создать купон для пользователя {user_id}")
        await _edit_message_safely(bot, callback.message, "Произошла внутренняя ошибка. Попробуйте позже.")
        return

    user_data = {
        "tg_id": user_id,
        "username": callback.from_user.username,
        "first_name": callback.from_user.first_name,
        "last_name": callback.from_user.last_name,
        "language_code": callback.from_user.language_code,
        "is_bot": callback.from_user.is_bot,
    }

    try:
        await activate_coupon(
            callback.message, state, session, coupon_code, admin=False, user_data=user_data
        )
        await mark_bonus_as_received(session, user_id)
    except Exception as e:
        logger.error(f"[Subscription Bonus] Ошибка активации купона для {user_id}: {e}", exc_info=True)
        await _edit_message_safely(bot, callback.message, "Не удалось активировать бонус. Попробуйте позже.")
        return

    try:
        await callback.message.delete()
    except TelegramBadRequest:
        logger.warning(f"Не удалось удалить сообщение {callback.message.message_id} для пользователя {user_id}")


if BONUS_ENABLE:
    try:
        from hooks.hooks import register_hook

        if SHOW_BUTTON_IN_PROFILE:
            register_hook("profile_menu", register_bonus_button)
            logger.info("[Subscription Bonus] Кнопка в профиле зарегистрирована.")
        else:
            logger.info("[Subscription Bonus] Кнопка в профиле отключена в конфиге.")

        register_hook("after_key_created", bonus_after_key_creation)
        logger.info("[Subscription Bonus] Модуль бонуса за подписку успешно зарегистрирован.")

    except ImportError:
        logger.error("[Subscription Bonus] Не удалось импортировать 'hooks' для регистрации модуля.")