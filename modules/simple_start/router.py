import os

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import REMNAWAVE_WEBAPP
from database import get_user_snapshot
from database.keys import get_keys
from handlers.utils import edit_or_send_message
from hooks.hooks import register_hook
from logger import logger

from . import texts
from .settings import ENABLED

router = Router()

_original_show_start_menu = None
_patched = False


async def _show_simple_start(message: Message, session):
    """Показывает упрощённое меню для пользователей без триала."""
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=texts.BTN_GET_KEY, callback_data="simple_start|get_key"))

    image_path = os.path.join("img", "pic.jpg")
    await edit_or_send_message(
        message,
        texts.WELCOME_TEXT,
        reply_markup=kb.as_markup(),
        media_path=image_path,
    )


def patch_show_start_menu():
    """Патчим функцию show_start_menu для перехвата новых пользователей."""
    global _original_show_start_menu, _patched

    if _patched:
        logger.warning("[SimpleStart] show_start_menu уже пропатчена, пропускаем")
        return

    try:
        import handlers.start
    except ImportError:
        logger.error("[SimpleStart] Не удалось импортировать handlers.start")
        return

    if not hasattr(handlers.start, 'show_start_menu'):
        logger.error("[SimpleStart] Функция show_start_menu не найдена в handlers.start")
        return

    _original_show_start_menu = handlers.start.show_start_menu
    logger.info("[SimpleStart] Сохранена оригинальная show_start_menu")

    async def wrapped_show_start_menu(
        message: Message,
        admin: bool,
        session,
        trial: int | None = None,
        key_count: int | None = None,
    ):
        """Обёртка для перехвата пользователей без триала."""
        if not ENABLED:
            await _original_show_start_menu(message, admin, session, trial, key_count)
            return

        # Получаем данные пользователя если не переданы
        if trial is None or key_count is None:
            snapshot = await get_user_snapshot(session, message.chat.id)
            if snapshot is not None:
                trial, key_count = snapshot
            else:
                trial, key_count = 0, 0

        # Если триал не использован (trial == 0) и нет ключей — показываем простое меню
        if trial == 0 and key_count == 0:
            logger.info(f"[SimpleStart] Показываем простое меню для {message.chat.id}")
            await _show_simple_start(message, session)
            return

        # Иначе — стандартное меню
        await _original_show_start_menu(message, admin, session, trial, key_count)

    handlers.start.show_start_menu = wrapped_show_start_menu

    _patched = True
    logger.info("[SimpleStart] Патчинг завершён")


# Патчим при загрузке модуля
patch_show_start_menu()


async def intercept_key_creation_hook(chat_id=None, session=None, target_message=None, **kwargs):
    """
    Хук для перехвата сообщения после создания ключа.
    Возвращает True чтобы предотвратить стандартное сообщение.
    """
    if not ENABLED:
        return None

    from database.tariffs import get_tariffs

    # Получаем ключи пользователя
    keys = await get_keys(session, chat_id)
    if not keys:
        return None

    # Проверяем, есть ли только один ключ (первый триал)
    if len(keys) != 1:
        return None

    key_obj = keys[0]

    # Проверяем что это триальный ключ (через tariff_id)
    if key_obj.tariff_id:
        trial_tariffs = await get_tariffs(session, group_code="trial")
        trial_tariff_ids = [t["id"] for t in trial_tariffs] if trial_tariffs else []
        if key_obj.tariff_id not in trial_tariff_ids:
            return None
    else:
        # Если нет tariff_id - не перехватываем
        return None

    key_name = key_obj.email
    final_link = key_obj.key or key_obj.remnawave_link

    kb = InlineKeyboardBuilder()

    # Кнопка подключения устройства
    if REMNAWAVE_WEBAPP and final_link and str(final_link).startswith("http"):
        kb.row(InlineKeyboardButton(text=texts.BTN_CONNECT_DEVICE, web_app=WebAppInfo(url=final_link)))
    else:
        kb.row(InlineKeyboardButton(text=texts.BTN_CONNECT_DEVICE, callback_data=f"connect_device|{key_name}"))

    # Определяем message из target_message
    if hasattr(target_message, "message"):
        message = target_message.message
    else:
        message = target_message

    image_path = os.path.join("img", "pic.jpg")
    await edit_or_send_message(
        message,
        texts.KEY_RECEIVED_TEXT,
        reply_markup=kb.as_markup(),
        media_path=image_path,
    )

    logger.info(f"[SimpleStart] Показано сообщение с кнопкой подключения для {chat_id}")
    return True  # Перехватываем, не показываем стандартное сообщение


register_hook("intercept_key_creation_message", intercept_key_creation_hook)
logger.info("[SimpleStart] Модуль загружен")


@router.callback_query(F.data == "simple_start|get_key")
async def get_trial_key(callback: CallbackQuery, state: FSMContext, session):
    """Выдаёт триальный ключ и показывает кнопку подключения."""
    from database import add_user, check_user_exists

    # Совместимость с v.5 и dev ветками
    try:
        from handlers.keys.key_create import handle_key_creation
    except ImportError:
        try:
            from handlers.keys.key_mode.key_create import handle_key_creation
        except ImportError:
            logger.error("[SimpleStart] Не удалось импортировать handle_key_creation")
            await callback.answer("Ошибка загрузки модуля", show_alert=True)
            return

    tg_id = callback.from_user.id

    # Удаляем первое сообщение
    try:
        await callback.message.delete()
    except Exception as e:
        logger.debug(f"[SimpleStart] Не удалось удалить сообщение: {e}")

    # Проверяем/создаём пользователя
    if not await check_user_exists(session, tg_id):
        await add_user(
            session=session,
            tg_id=tg_id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
            last_name=callback.from_user.last_name,
            language_code=callback.from_user.language_code,
        )

    # Сохраняем флаг для перехвата сообщения после создания ключа
    await state.update_data(simple_start_flow=True)

    # Создаём фейковое сообщение для handle_key_creation (чтобы отправить новое, а не редактировать)
    await handle_key_creation(tg_id, state, session, callback)
    await callback.answer()


@router.callback_query(F.data == "simple_start|connect")
async def show_connect_device(callback: CallbackQuery, session):
    """Показывает экран с кнопкой подключения устройства."""
    tg_id = callback.from_user.id

    # Получаем последний ключ пользователя
    keys = await get_keys(session, tg_id)
    if not keys:
        await callback.answer("Ключ не найден", show_alert=True)
        return

    key_record = keys[0]
    key_name = key_record.get("email")
    final_link = key_record.get("key") or key_record.get("remnawave_link")

    kb = InlineKeyboardBuilder()

    # Кнопка подключения устройства
    if REMNAWAVE_WEBAPP and final_link and final_link.startswith("http"):
        kb.row(InlineKeyboardButton(text=texts.BTN_CONNECT_DEVICE, web_app=WebAppInfo(url=final_link)))
    else:
        kb.row(InlineKeyboardButton(text=texts.BTN_CONNECT_DEVICE, callback_data=f"connect_device|{key_name}"))

    image_path = os.path.join("img", "pic.jpg")
    await edit_or_send_message(
        callback.message,
        texts.KEY_RECEIVED_TEXT,
        reply_markup=kb.as_markup(),
        media_path=image_path,
    )
    await callback.answer()
