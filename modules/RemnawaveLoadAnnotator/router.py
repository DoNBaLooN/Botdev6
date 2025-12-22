from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from html import escape
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import aiohttp

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from config import (
    REMNAWAVE_ACCESS_TOKEN,
    REMNAWAVE_LOGIN,
    REMNAWAVE_PASSWORD,
    REMNAWAVE_TOKEN_LOGIN_ENABLED,
)
from database import async_session_maker
from database.models import Server
from filters.admin import IsAdminFilter
from logger import logger

from . import settings
from hooks.hooks import register_hook


router = Router()

HOST_LIST_CALLBACK = "admin_panel:remnawave_hosts"
ADMIN_PANEL_BACK_CALLBACK = "admin_panel:admin:1"

CPU_LINE_RE = re.compile(r'^node_cpu_seconds_total\\{[^}]*cpu="(\\d+)"[^}]*\\}\\s+([0-9.eE+-]+)$')
SUFFIX_RE = re.compile(r"\\s+·\\s+.*?\\d{1,3}%$", re.UNICODE)
PERCENT_RE = re.compile(r"(\\d{1,3})%$", re.UNICODE)


@dataclass(frozen=True)
class NodeConfig:
    title: str
    endpoint: str
    uuid: str

    @property
    def key(self) -> tuple[str, str]:
        return self.title, self.endpoint


@dataclass(frozen=True)
class RemnawaveHost:
    title: str
    uuid: str


def _load_nodes() -> list[NodeConfig]:
    nodes: list[NodeConfig] = []
    for raw in settings.NODES:
        try:
            node = NodeConfig(
                title=raw["title"].strip(),
                endpoint=raw["endpoint"].strip(),
                uuid=raw["uuid"].strip(),
            )
        except KeyError as exc:  # pragma: no cover - defensive logging
            logger.warning("[RemnawaveLoadAnnotator] Пропуск некорректной ноды (нет ключа %s): %s", exc, raw)
            continue
        if not node.title or not node.endpoint or not node.uuid:
            logger.warning("[RemnawaveLoadAnnotator] Пропуск ноды с пустыми значениями: %s", raw)
            continue
        nodes.append(node)
    return nodes


NODES = _load_nodes()


def _status_emoji(pct: int) -> str:
    if pct < 15:
        return "🟢"
    if pct < 40:
        return "🟢"
    if pct < 70:
        return "🟠"
    if pct < 90:
        return "🔴"
    return "🧨"


def _strip_suffix(remark: str | None) -> str:
    if not remark:
        return ""
    return SUFFIX_RE.sub("", remark.strip())


def _build_remark(base: str, pct: int) -> str:
    emoji = _status_emoji(pct)
    suffix = f" · {emoji}{pct}%"
    base = (base or "").strip()
    max_base_len = max(0, settings.MAX_REMARK_LEN - len(suffix))
    if len(base) > max_base_len:
        cut = max(0, max_base_len - 1)
        base = f"{base[:cut]}…" if cut > 0 else ""
    return f"{base}{suffix}"


def _extract_percent(remark: str) -> int | None:
    match = PERCENT_RE.search(remark)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:  # pragma: no cover - defensive logging
        return None


def _count_cores(metrics_text: str) -> int:
    cpus = set()
    for line in metrics_text.splitlines():
        if line.startswith("#"):
            continue
        match = CPU_LINE_RE.match(line)
        if match:
            cpus.add(match.group(1))
    return max(1, len(cpus))


def _parse_load5(metrics_text: str) -> float | None:
    for line in metrics_text.splitlines():
        if not line or line.startswith("#"):
            continue
        if line.startswith("node_load5 "):
            parts = line.split()
            if len(parts) >= 2:
                try:
                    return float(parts[1])
                except ValueError:
                    return None
    return None


def _percent_from_load_per_core(load5: float, cores: int) -> int:
    cores = max(1, int(cores))
    per_core = load5 / cores

    if not settings.SCALE_PER_CORE:
        x = max(0.0, min(1.0, per_core))
        return int(round(x * 100))

    rng = max(1e-9, settings.PER_CORE_MAX - settings.PER_CORE_MIN)
    x = (per_core - settings.PER_CORE_MIN) / rng
    x = max(0.0, min(1.0, x))
    return int(round(x * 100))


def _normalize_metrics_url(endpoint: str) -> str:
    url = endpoint
    if not url.startswith("http://") and not url.startswith("https://"):
        url = f"http://{url}"
    if not url.endswith("/metrics"):
        url = url.rstrip("/") + "/metrics"
    return url


async def _fetch_metrics(session: aiohttp.ClientSession, endpoint: str) -> str | None:
    url = _normalize_metrics_url(endpoint)
    try:
        async with session.get(url) as response:
            if response.status >= 400:
                logger.error("[RemnawaveLoadAnnotator] node_exporter %s вернул %s", endpoint, response.status)
                return None
            return await response.text()
    except Exception as exc:  # noqa: BLE001
        logger.error("[RemnawaveLoadAnnotator] node_exporter %s недоступен: %s", endpoint, exc)
        return None


async def _fetch_node_loads() -> dict[tuple[str, str], tuple[float, int]]:
    if not NODES:
        return {}

    result: dict[tuple[str, str], tuple[float, int]] = {}
    timeout = aiohttp.ClientTimeout(total=settings.CONNECT_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for node in NODES:
            metrics = await _fetch_metrics(session, node.endpoint)
            if not metrics:
                continue

            load5 = _parse_load5(metrics)
            if load5 is None:
                logger.warning(
                    "[RemnawaveLoadAnnotator] Не найдено node_load5 у %s (%s)",
                    node.title,
                    node.endpoint,
                )
                continue

            cores = _count_cores(metrics)
            pct = _percent_from_load_per_core(load5, cores)
            result[node.key] = (load5, pct)
            logger.debug(
                "[RemnawaveLoadAnnotator] node_exporter %s (%s): load5=%.2f, cores=%s => %s%%",
                node.title,
                node.endpoint,
                load5,
                cores,
                pct,
            )
    logger.info("[RemnawaveLoadAnnotator] Опрос node_exporter завершён: %s нод", len(result))
    return result


def _is_auth_configured() -> bool:
    if REMNAWAVE_TOKEN_LOGIN_ENABLED:
        return bool(REMNAWAVE_ACCESS_TOKEN)
    return bool(REMNAWAVE_LOGIN and REMNAWAVE_PASSWORD)


def _build_panel_base(api_url: str) -> str:
    parts = urlsplit(api_url)
    if parts.scheme and parts.netloc:
        return urlunsplit((parts.scheme, parts.netloc, "", "", "")).rstrip("/")
    return api_url.rstrip("/")


async def _fetch_panel_base_url() -> str | None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Server.api_url).where(Server.panel_type == "remnawave").limit(1)
        )
        api_url = result.scalar_one_or_none()
    if not api_url:
        return None
    return _build_panel_base(api_url)


def _remnawave_session_kwargs() -> dict[str, Any] | None:
    headers: dict[str, str] = {"Accept": "application/json"}
    auth: aiohttp.BasicAuth | None = None

    if REMNAWAVE_TOKEN_LOGIN_ENABLED:
        if not REMNAWAVE_ACCESS_TOKEN:
            return None
        headers["Authorization"] = f"Bearer {REMNAWAVE_ACCESS_TOKEN}"
    else:
        if not REMNAWAVE_LOGIN or not REMNAWAVE_PASSWORD:
            return None
        auth = aiohttp.BasicAuth(REMNAWAVE_LOGIN, REMNAWAVE_PASSWORD)

    kwargs: dict[str, Any] = {"headers": headers}
    if auth is not None:
        kwargs["auth"] = auth
    return kwargs


async def _remna_get_host(session: aiohttp.ClientSession, base_url: str, uuid: str) -> dict[str, Any]:
    url = f"{base_url}/api/hosts/{uuid}"
    async with session.get(url) as response:
        response.raise_for_status()
        payload = await response.json()
        return payload.get("response", {})


async def _remna_patch_host(
    session: aiohttp.ClientSession,
    base_url: str,
    uuid: str,
    new_remark: str,
) -> dict[str, Any]:
    url = f"{base_url}/api/hosts"
    async with session.patch(url, json={"uuid": uuid, "remark": new_remark}) as response:
        if response.status >= 400:
            text = await response.text()
            raise RuntimeError(f"PATCH {url} {response.status}: {text}")
        payload = await response.json()
        return payload.get("response", {})


async def _remna_list_hosts(session: aiohttp.ClientSession, base_url: str) -> list[RemnawaveHost]:
    url = f"{base_url}/api/hosts"
    async with session.get(url) as response:
        if response.status >= 400:
            text = await response.text()
            raise RuntimeError(f"GET {url} {response.status}: {text}")
        payload = await response.json()

    items = payload.get("response") or []
    hosts: list[RemnawaveHost] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        uuid = (item.get("uuid") or "").strip()
        if not uuid:
            continue
        remark = _strip_suffix(item.get("remark"))
        address = (item.get("address") or "").strip()
        title = (remark or "").strip() or address or "Без названия"
        hosts.append(RemnawaveHost(title=title, uuid=uuid))

    logger.info("[RemnawaveLoadAnnotator] Получено %s хостов из Remnawave API", len(hosts))
    return hosts


async def _fetch_remnawave_hosts_list() -> list[RemnawaveHost]:
    if not _is_auth_configured():
        raise ValueError("Не настроены данные авторизации Remnawave.")

    base_url = await _fetch_panel_base_url()
    if not base_url:
        raise ValueError("Не найден api_url панели Remnawave в базе данных.")

    session_kwargs = _remnawave_session_kwargs()
    if session_kwargs is None:
        raise ValueError("Некорректные настройки авторизации Remnawave.")

    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout, **session_kwargs) as session:
        return await _remna_list_hosts(session, base_url)


def _format_hosts_text(hosts: list[RemnawaveHost]) -> str:
    if not hosts:
        return "⚠️ Не найдено доступных хостов Remnawave."

    entries = [
        f"• {escape(host.title) if host.title else '—'}\n<code>{escape(host.uuid)}</code>"
        for host in hosts
    ]
    header = "📋 <b>Список хостов Remnawave</b>"
    return f"{header}\n\n" + "\n\n".join(entries)


@register_hook("admin_panel")
def admin_panel_hook(**_: Any):
    button = InlineKeyboardButton(text="📋 Хосты Remnawave", callback_data=HOST_LIST_CALLBACK)
    return {"after": "admin_panel:modules:1", "button": button}


@router.callback_query(F.data == HOST_LIST_CALLBACK, IsAdminFilter())
async def handle_hosts_list(callback: CallbackQuery) -> None:
    await callback.answer()

    back_markup = (
        InlineKeyboardBuilder()
        .row(InlineKeyboardButton(text="⬅️ Назад", callback_data=ADMIN_PANEL_BACK_CALLBACK))
        .as_markup()
    )

    try:
        hosts = await _fetch_remnawave_hosts_list()
    except ValueError as exc:
        logger.info("[RemnawaveLoadAnnotator] Список хостов недоступен: %s", exc)
        text = f"⚠️ {escape(str(exc))}"
    except Exception as exc:  # noqa: BLE001
        logger.exception("[RemnawaveLoadAnnotator] Ошибка при получении списка хостов: %s", exc)
        text = "❌ Не удалось получить список хостов Remnawave. Проверьте настройки и повторите попытку."
    else:
        text = _format_hosts_text(hosts)

    if callback.message is None:
        return

    try:
        await callback.message.edit_text(
            text=text,
            reply_markup=back_markup,
            parse_mode=ParseMode.HTML,
        )
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return
        raise


async def _process_once() -> None:
    if not NODES:
        logger.info("[RemnawaveLoadAnnotator] Список нод пуст, итерация пропущена")
        return

    if not _is_auth_configured():
        logger.error("[RemnawaveLoadAnnotator] Не заданы учётные данные для Remnawave API")
        return

    base_url = await _fetch_panel_base_url()
    if not base_url:
        logger.warning("[RemnawaveLoadAnnotator] Не найден api_url панели Remnawave в БД")
        return

    loads = await _fetch_node_loads()
    if not loads:
        logger.warning("[RemnawaveLoadAnnotator] Нет данных от node_exporter")
        return

    session_kwargs = _remnawave_session_kwargs()
    if session_kwargs is None:
        logger.error("[RemnawaveLoadAnnotator] Некорректные настройки авторизации Remnawave")
        return

    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout, **session_kwargs) as session:
        for node in NODES:
            load = loads.get(node.key)
            if not load:
                logger.info(
                    "[RemnawaveLoadAnnotator] Пропуск: нет метрики для %s (%s)",
                    node.title,
                    node.endpoint,
                )
                continue

            load5, pct = load
            try:
                host = await _remna_get_host(session, base_url, node.uuid)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "[RemnawaveLoadAnnotator] GET host %s (%s) не удался: %s",
                    node.title,
                    node.uuid,
                    exc,
                )
                continue

            current_remark = (host.get("remark") or "").strip()
            base_remark = _strip_suffix(current_remark) or node.title
            new_remark = _build_remark(base_remark, pct)

            if current_remark == new_remark:
                logger.debug(
                    "[RemnawaveLoadAnnotator] Без изменений: %s (%s): %s",
                    node.title,
                    node.uuid,
                    new_remark,
                )
                continue

            old_pct = _extract_percent(current_remark)
            if old_pct is not None and abs(old_pct - pct) < settings.DELTA_MIN:
                logger.debug(
                    "[RemnawaveLoadAnnotator] Изменение < %s%%: %s (%s): %s -> %s",
                    settings.DELTA_MIN,
                    node.title,
                    node.uuid,
                    current_remark,
                    new_remark,
                )
                continue

            try:
                await _remna_patch_host(session, base_url, node.uuid, new_remark)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "[RemnawaveLoadAnnotator] PATCH host %s (%s) не удался: %s",
                    node.title,
                    node.uuid,
                    exc,
                )
                continue

            logger.info(
                "[RemnawaveLoadAnnotator] Обновлён %s (%s): %s (load5=%.2f → %s%%)",
                node.title,
                node.uuid,
                new_remark,
                load5,
                pct,
            )


async def _monitor_loop() -> None:
    logger.info(
        "[RemnawaveLoadAnnotator] Мониторинг запущен. interval=%s LOG_SCALE=%s",
        settings.INTERVAL_SEC,
        "on" if settings.SCALE_PER_CORE else "off",
    )
    while True:
        try:
            await _process_once()
        except asyncio.CancelledError:  # pragma: no cover - task cancellation
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("[RemnawaveLoadAnnotator] Итерация завершилась с ошибкой: %s", exc)
        await asyncio.sleep(settings.INTERVAL_SEC)


@router.startup()
async def _startup(_: Bot) -> None:
    if not settings.ENABLED:
        logger.info("[RemnawaveLoadAnnotator] Модуль отключён (settings.ENABLED = False)")
        return
    if not NODES:
        logger.info("[RemnawaveLoadAnnotator] Мониторинг не запущен: список нод пуст")
        return
    if not _is_auth_configured():
        logger.info("[RemnawaveLoadAnnotator] Мониторинг не запущен: не настроены данные авторизации Remnawave")
        return
    asyncio.create_task(_monitor_loop())
