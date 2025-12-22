from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from . import settings


def progress_keyboard(claimable: dict | None, channel_bonus_claimed: bool) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    if claimable:
        builder.row(
            InlineKeyboardButton(
                text="Получить награду",
                callback_data=f"achv|claim|{claimable['steps']}",
            )
        )
    if not channel_bonus_claimed:
        # Кнопка "Открыть канал" (URL) + "Проверить канал"
        if settings.ACHV.get("ANNOUNCE_CHANNEL_LINK"):
            builder.row(
                InlineKeyboardButton(text="Открыть канал", url=settings.ACHV["ANNOUNCE_CHANNEL_LINK"]),
                InlineKeyboardButton(text="Проверить канал", callback_data="achv|check_channel"),
            )
        else:
            builder.row(
                InlineKeyboardButton(text="Проверить канал", callback_data="achv|check_channel")
            )
    builder.row(InlineKeyboardButton(text="🎁 Награды", callback_data="achv|rewards"))
    builder.row(InlineKeyboardButton(text="📊 За что ступени", callback_data="achv|breakdown"))
    builder.row(
        InlineKeyboardButton(text="🏆 ТОП-5", callback_data="achv|top")
    )
    builder.row(InlineKeyboardButton(text="ℹ️ Что делать", callback_data="achv|howto"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="achv|back"))
    return builder


def top_keyboard() -> InlineKeyboardBuilder:
    return back_to_progress_keyboard()


def rewards_keyboard() -> InlineKeyboardBuilder:
    return back_to_progress_keyboard()


def back_to_progress_keyboard() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="achv|open"))
    return builder
