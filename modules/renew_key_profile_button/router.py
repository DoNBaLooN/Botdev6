from aiogram import Router
from aiogram.types import InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession

from database.keys import get_keys
from hooks.hooks import register_hook

from . import texts

router = Router(name="renew_key_profile_button")


async def _pick_key_for_renewal(keys: list) -> str | None:
    eligible_keys = [key for key in keys if getattr(key, "email", None)]
    if not eligible_keys:
        return None

    def sort_key(key):
        expiry_time = getattr(key, "expiry_time", None)
        created_at = getattr(key, "created_at", None)
        return (
            expiry_time if isinstance(expiry_time, int) else float("inf"),
            created_at if isinstance(created_at, int) else float("inf"),
        )

    chosen = min(eligible_keys, key=sort_key)
    return chosen.email


async def profile_menu_hook(*, chat_id: int | None = None, session: AsyncSession | None = None, **kwargs):
    if chat_id is None or session is None:
        return None

    keys = await get_keys(session, chat_id)
    key_email = await _pick_key_for_renewal(keys)
    if not key_email:
        return None

    return {
        "insert_at": 0,
        "button": InlineKeyboardButton(
            text=texts.RENEW_BUTTON_TEXT,
            callback_data=f"renew_key|{key_email}",
        ),
    }


register_hook("profile_menu", profile_menu_hook)
