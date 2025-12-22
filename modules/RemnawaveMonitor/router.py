import asyncio
import logging

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import aiohttp

from aiogram import Bot, Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
)
from sqlalchemy import select

from config import (
    ADMIN_ID,
    REMNAWAVE_ACCESS_TOKEN,
    REMNAWAVE_LOGIN,
    REMNAWAVE_PASSWORD,
    REMNAWAVE_TOKEN_LOGIN_ENABLED,
)
from database import async_session_maker
from database.models import Admin, Server
from handlers.buttons import MAIN_MENU
from middlewares import maintenance
from middlewares.maintenance import MaintenanceModeMiddleware

from . import settings, texts
from .db import add_attempt, add_day_subscription, clear_attempts, get_attempted_users


router = Router()
logger = logging.getLogger(__name__)

maintenance_start: datetime | None = None
manual_maintenance_active = False
manual_maintenance_start: datetime | None = None

ERROR_HINTS: dict[str, str] = {
    "HTTP 500": "Внутренняя ошибка панели. Проверь логи Remnawave и состояние БД.",
    "HTTP 502": "Bad Gateway. Проверь прокси/балансировщик перед панелью (nginx, caddy, L7).",
    "HTTP 503": "Service Unavailable. Возможен перезапуск/обновление или перегрузка сервера.",
    "HTTP 504": "Gateway Timeout. Нет ответа от бэкенда. Проверь сеть/БД/нагрузку.",
    "401": "Unauthorized. Проверь логин/пароль или актуальность Bearer-токена.",
    "403": "Forbidden. Проверь права доступа и токен, возможны ACL/файрвол.",
    "ServerDisconnectedError": "Сервер оборвал соединение. Проверь аптайм сервиса и его логи.",
    "TimeoutError": "Таймаут (10 сек). Проверь нагрузку CPU/IO и медленные запросы к БД.",
    "ClientConnectorError": "Нет подключения. Проверь, запущен ли сервис и открыт ли порт.",
    "gaierror": "Ошибка DNS. Проверь, резолвится ли домен панели на сервере бота.",
    "SSLError": "Ошибка TLS/SSL. Проверь сертификаты и HTTPS-настройки (chain/privkey).",
}

def _hint_for_error(err: str) -> str | None:
    for key, hint in ERROR_HINTS.items():
        if key in err:
            return hint
    return None

_original_mm_call = MaintenanceModeMiddleware.__call__


async def _patched_mm_call(
    self,
    handler: Callable[[Update, dict[str, Any]], Awaitable[Any]],
    event: Update,
    data: dict[str, Any],
) -> Any:
    user_id = None
    if maintenance.maintenance_mode:
        if isinstance(event, Message):
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id

        if user_id and user_id not in ADMIN_ID:
            async with async_session_maker() as session:
                db_admin = await session.get(Admin, user_id)
                if not db_admin:
                    await add_attempt(session, user_id)

    return await _original_mm_call(self, handler, event, data)


MaintenanceModeMiddleware.__call__ = _patched_mm_call


async def _fetch_api_url() -> str | None:
    async with async_session_maker() as session:
        result = await session.execute(select(Server.api_url).where(Server.panel_type == "remnawave").limit(1))
        return result.scalar_one_or_none()


async def _notify_admins(bot: Bot, message: str) -> None:
    ids: set[int] = set(ADMIN_ID)
    async with async_session_maker() as session:
        result = await session.execute(select(Admin.tg_id))
        ids.update(row[0] for row in result.all())

    for admin_id in ids:
        try:
            await bot.send_message(admin_id, message)
        except Exception as e:
            logger.warning("Failed to notify admin %s: %s", admin_id, e)


async def _notify_users(bot: Bot, bonus: bool) -> None:
    async with async_session_maker() as session:
        ids = await get_attempted_users(session)
    for user_id in ids:
        try:
            text = texts.BOT_AVAILABLE
            if bonus:
                text = f"{text}\n\n{texts.PATIENCE_BONUS_TEXT}"
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text=MAIN_MENU, callback_data="profile")]]
            )
            await bot.send_message(user_id, text, reply_markup=keyboard)
            if bonus:
                async with async_session_maker() as session:
                    await add_day_subscription(session, user_id)
        except Exception as e:
            logger.warning("Failed to notify user %s: %s", user_id, e)
    async with async_session_maker() as session:
        await clear_attempts(session, ids)


async def _finalize_maintenance_window(
    bot: Bot,
    *,
    started_at: datetime | None,
    notify_admins: bool,
) -> tuple[int, bool]:
    attempts_count = 0
    attempted_ids: list[int] | None = None
    try:
        async with async_session_maker() as session:
            attempted_ids = await get_attempted_users(session)
        attempts_count = len(attempted_ids)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Failed to read attempted users count: %s", exc)
        attempted_ids = None

    bonus = False
    if settings.PATIENCE_BONUS_ENABLED and started_at:
        downtime = datetime.utcnow() - started_at
        if downtime.total_seconds() >= settings.PATIENCE_BONUS_THRESHOLD_MINUTES * 60:
            bonus = True

    if notify_admins:
        admin_msg = f"{texts.PANEL_AVAILABLE}\n\nЗа время техработ пытались зайти: {attempts_count}"
        await _notify_admins(bot, admin_msg)

    if settings.NOTIFY_USERS:
        await _notify_users(bot, bonus)
    else:
        ids_to_handle: list[int]
        if attempted_ids is None:
            try:
                async with async_session_maker() as session:
                    ids_to_handle = await get_attempted_users(session)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.warning("Failed to collect attempted users for cleanup: %s", exc)
                ids_to_handle = []
        else:
            ids_to_handle = attempted_ids

        if bonus:
            for user_id in ids_to_handle:
                async with async_session_maker() as session:
                    await add_day_subscription(session, user_id)

        async with async_session_maker() as session:
            await clear_attempts(session, ids_to_handle)

    return attempts_count, bonus


async def _check_panel(api_url: str) -> tuple[bool, str | None]:
    kwargs: dict = {"timeout": aiohttp.ClientTimeout(total=10)}
    headers = {}
    auth = None
    if REMNAWAVE_TOKEN_LOGIN_ENABLED and REMNAWAVE_ACCESS_TOKEN:
        headers["Authorization"] = f"Bearer {REMNAWAVE_ACCESS_TOKEN}"
    else:
        auth = aiohttp.BasicAuth(REMNAWAVE_LOGIN, REMNAWAVE_PASSWORD)

    try:
        async with aiohttp.ClientSession(auth=auth) as session:
            async with session.get(api_url, headers=headers, **kwargs) as resp:
                logger.info("Remnawave API %s responded with %s", api_url, resp.status)
                if resp.status < 500:
                    return True, None
                return False, f"HTTP {resp.status}"
    except aiohttp.ServerDisconnectedError:
        fixed_url = api_url if api_url.endswith("/") else api_url + "/"
        try:
            async with aiohttp.ClientSession(auth=auth) as session:
                async with session.get(fixed_url, headers=headers, **kwargs) as resp:
                    if resp.status < 500:
                        logger.info("Remnawave API %s OK", fixed_url)
                        return True, None
                    logger.warning("Remnawave API %s returned %s after retry", fixed_url, resp.status)
                    return False, f"HTTP {resp.status}"
        except Exception as e2:
            logger.warning("Remnawave API retry failed: %s", e2)
            return False, str(e2)
    except Exception as e:
        logger.warning("Remnawave API check failed: %s", e)
        return False, str(e)


async def _monitor_panel(bot: Bot) -> None:
    global maintenance_start, manual_maintenance_active, manual_maintenance_start
    panel_available = True
    while True:
        api_url = await _fetch_api_url()
        if not api_url:
            logger.warning("Remnawave API URL not found in database")
        else:
            is_available, error_msg = await _check_panel(api_url)
            if not is_available:
                for i in range(settings.RETRY_COUNT):
                    await asyncio.sleep(settings.RETRY_DELAY)
                    retry_ok, retry_err = await _check_panel(api_url)
                    if retry_ok:
                        is_available, error_msg = True, None
                        break
                    else:
                        error_msg = retry_err

            if is_available and maintenance.maintenance_mode and panel_available and not manual_maintenance_active:
                manual_maintenance_active = True
                manual_maintenance_start = datetime.utcnow()
                logger.info("Manual maintenance mode enabled while panel is available")

            if manual_maintenance_active and not maintenance.maintenance_mode:
                attempts_count, bonus = await _finalize_maintenance_window(
                    bot,
                    started_at=manual_maintenance_start,
                    notify_admins=False,
                )
                manual_maintenance_active = False
                manual_maintenance_start = None
                maintenance_start = None
                logger.info(
                    "Manual maintenance mode disabled. attempts=%s, bonus_awarded=%s",
                    attempts_count,
                    bonus,
                )

            if is_available and not panel_available:
                panel_available = True
                maintenance.maintenance_mode = False
                manual_maintenance_active = False
                manual_maintenance_start = None
                attempts_count, bonus = await _finalize_maintenance_window(
                    bot,
                    started_at=maintenance_start,
                    notify_admins=True,
                )
                maintenance_start = None
                logger.info(
                    "Automatic maintenance window closed. attempts=%s, bonus_awarded=%s",
                    attempts_count,
                    bonus,
                )
            elif not is_available and panel_available:
                panel_available = False
                maintenance.maintenance_mode = True
                maintenance_start = datetime.utcnow()
                manual_maintenance_active = False
                manual_maintenance_start = None
                msg = texts.PANEL_UNAVAILABLE
                if error_msg:
                    msg += f"\n\nПричина: {error_msg}"
                    hint = _hint_for_error(error_msg)
                    if hint:
                        msg += f"\nЧто проверить: {hint}"
                await _notify_admins(bot, msg)
        await asyncio.sleep(settings.CHECK_INTERVAL)


@router.startup()
async def _startup(bot: Bot) -> None:
    if not settings.ENABLED:
        logger.info("Remnawave monitor module is DISABLED via settings.ENABLED=false")
        return
    asyncio.create_task(_monitor_panel(bot))
