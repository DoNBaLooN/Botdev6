from aiogram import Router
from aiogram.types import InlineKeyboardButton

from hooks.hooks import register_hook
from logger import logger


router = Router(name="buy_button_profile")


async def _profile_menu_buy_button(chat_id: int, admin: bool, session, **kwargs):
    try:
        from database import get_key_count

        key_count = await get_key_count(session, chat_id)
        if key_count <= 0:
            return None

        # Place at the very top of the profile menu (index 0)
        return {"insert_at": 0, "button": InlineKeyboardButton(text="🔌 Купить подписку", callback_data="buy")}
    except Exception as e:
        try:
            logger.error(f"[buy_button_profile] Failed to build profile menu button: {e}")
        except Exception:
            pass
        return None


register_hook("profile_menu", _profile_menu_buy_button)

