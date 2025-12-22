from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from . import texts


def broadcast_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.BTN_OPEN_DISCOUNTS, callback_data="discounts_broadcast|open")
    builder.adjust(1)
    return builder.as_markup()
