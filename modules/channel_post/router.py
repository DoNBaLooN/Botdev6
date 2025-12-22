import json
import re

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import CHANNEL_ID
from filters.admin import IsAdminFilter
from hooks.hooks import register_hook
from logger import logger

# Избегаем импорта admin panel helperов на уровне модуля, чтобы не провоцировать циклические импорты


router = Router(name="channel_post_module")


class ChannelPostStates(StatesGroup):
    waiting_for_message = State()
    preview = State()


def parse_message_buttons(text: str) -> tuple[str, InlineKeyboardMarkup | None]:
    if "BUTTONS:" not in text:
        return text, None

    parts = text.split("BUTTONS:", 1)
    clean_text = parts[0].strip()
    buttons_text = parts[1].strip()

    if not buttons_text:
        return clean_text, None

    buttons = []
    button_lines = [line.strip() for line in buttons_text.split("\n") if line.strip()]

    for line in button_lines:
        try:
            cleaned_line = re.sub(r'<tg-emoji emoji-id="[^"]*">([^<]*)</tg-emoji>', r"\1", line)
            button_data = json.loads(cleaned_line)

            if not isinstance(button_data, dict) or "text" not in button_data:
                logger.warning(f"[ChannelPost] Неверный формат кнопки: {line}")
                continue

            text_btn = button_data["text"]

            if "callback" in button_data:
                callback_data = button_data["callback"]
                if len(callback_data) > 64:
                    logger.warning(f"[ChannelPost] Callback слишком длинный: {callback_data}")
                    continue
                button = InlineKeyboardButton(text=text_btn, callback_data=callback_data)
            elif "url" in button_data:
                url = button_data["url"]
                button = InlineKeyboardButton(text=text_btn, url=url)
            else:
                logger.warning(f"[ChannelPost] Кнопка без действия: {line}")
                continue

            buttons.append([button])

        except json.JSONDecodeError as e:
            logger.warning(f"[ChannelPost] Ошибка парсинга JSON кнопки: {line} - {e}")
            continue
        except Exception as e:
            logger.error(f"[ChannelPost] Ошибка создания кнопки: {line} - {e}")
            continue

    if not buttons:
        return clean_text, None

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    return clean_text, keyboard


async def admin_panel_hook(admin_role: str, **kwargs):
    from .settings import ENABLE, BUTTON_TEXT
    if not ENABLE:
        return None
    # Используем прямую строку колбэка вместо AdminPanelCallback, чтобы исключить импорт
    btn = InlineKeyboardButton(text=BUTTON_TEXT, callback_data="admin_panel:channel_post:1")
    return {"after": "sender", "button": btn}


@router.callback_query(F.data.startswith("admin_panel:channel_post"), IsAdminFilter())
async def handle_channel_post_entry(callback_query: CallbackQuery, state: FSMContext):
    try:
        instructions_text = (
            "✍️ Введите контент поста для канала\n\n"
            "Поддерживается только Telegram-форматирование — <b>жирный</b>, <i>курсив</i> и другие стили через редактор Telegram.\n\n"
            "Вы можете отправить:\n"
            "• Только <b>текст</b>\n"
            "• Только <b>картинку</b>\n"
            "• <b>Текст + картинку</b>\n"
            "• <b>Сообщение + кнопки</b> (см. формат ниже)\n\n"
            "<b>📋 Пример формата кнопок:</b>\n"
            "<code>Ваше сообщение</code>\n\n"
            "<code>BUTTONS:</code>\n"
            "<code>{\"text\": \"👤 Личный кабинет\", \"callback\": \"profile\"}</code>\n"
            "<code>{\"text\": \"➕ Купить подписку\", \"callback\": \"buy\"}</code>\n"
            "<code>{\"text\": \"🎁 Забрать купон\", \"url\": \"https://t.me/cupons\"}</code>\n"
            "<code>{\"text\": \"📢 Канал\", \"url\": \"https://t.me/channel\"}</code>"
        )
        await callback_query.message.edit_text(
            text=instructions_text,
            reply_markup=InlineKeyboardBuilder().row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel:admin:1")).as_markup(),
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            logger.debug("[ChannelPost] Сообщение не изменено")
        else:
            raise

    # Установим состояние ожидания контента поста
    await state.set_state(ChannelPostStates.waiting_for_message)


@router.message(ChannelPostStates.waiting_for_message, IsAdminFilter())
async def handle_channel_post_message(message: Message, state: FSMContext):

    original_text = message.html_text or message.text or message.caption or ""
    photo = message.photo[-1].file_id if message.photo else None

    clean_text, keyboard = parse_message_buttons(original_text)

    max_len = 1024 if photo else 4096
    if len(clean_text) > max_len:
        back_kb = InlineKeyboardBuilder().row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel:admin:1")).as_markup()
        await message.answer(
            f"⚠️ Сообщение слишком длинное.\nМаксимум: <b>{max_len}</b> символов, сейчас: <b>{len(clean_text)}</b>.",
            reply_markup=back_kb,
        )
        await state.clear()
        return

    await state.update_data(text=clean_text, photo=photo, keyboard=keyboard.model_dump() if keyboard else None)
    await state.set_state(ChannelPostStates.preview)

    if photo:
        await message.answer_photo(photo=photo, caption=clean_text, parse_mode="HTML", reply_markup=keyboard)
    else:
        await message.answer(text=clean_text, parse_mode="HTML", reply_markup=keyboard)

    await message.answer(
        "👀 Это предпросмотр поста. Отправить в канал?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="📮 Опубликовать", callback_data="channel_post_send"), InlineKeyboardButton(text="❌ Отмена", callback_data="channel_post_cancel")]]
        ),
    )


@router.callback_query(F.data == "channel_post_send", IsAdminFilter())
async def handle_channel_post_send(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    text_message = data.get("text")
    photo = data.get("photo")
    keyboard_data = data.get("keyboard")

    keyboard = None
    if keyboard_data:
        try:
            keyboard = InlineKeyboardMarkup.model_validate(keyboard_data)
        except Exception as e:
            logger.error(f"[ChannelPost] Ошибка восстановления клавиатуры: {e}")

    try:
        if photo:
            await callback.bot.send_photo(chat_id=CHANNEL_ID, photo=photo, caption=text_message or "", parse_mode="HTML", reply_markup=keyboard)
        else:
            await callback.bot.send_message(chat_id=CHANNEL_ID, text=text_message or "", parse_mode="HTML", reply_markup=keyboard)
        await callback.message.edit_text(
            "✅ Пост опубликован в канале.",
            reply_markup=InlineKeyboardBuilder().row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel:admin:1")).as_markup(),
        )
    except TelegramBadRequest as e:
        await callback.message.answer(f"❌ Ошибка публикации: {e}")
    finally:
        await state.clear()


@router.callback_query(F.data == "channel_post_cancel", IsAdminFilter())
async def handle_channel_post_cancel(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "🚫 Публикация отменена.",
        reply_markup=InlineKeyboardBuilder().row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel:admin:1")).as_markup(),
    )
    await state.clear()


register_hook("admin_panel", admin_panel_hook)


