"""Настройки модуля офлайн-конверсий Яндекс.Метрики."""

from __future__ import annotations

# ⚠️ Ниже указаны системные параметры модуля.
# Не изменяйте их без необходимости — они уже оптимально настроены.

ENABLED: bool = True
# Используется как запасное значение для совместимости, если у счётчика не
# указан собственный START_PREFIX.
START_PREFIX: str = "utm_vlwb_"
ALLOW_INITIAL_BACKFILL: bool = False
EXTRA_PAYLOAD_TEMPLATE: dict[str, str] = {}


# --- Настройки Measurement Protocol ---

# ID счётчика Яндекс.Метрики, секрет токен и префикс старта можно указать в одной строке
# через запятую: "YA_TID,YA_MS,START_PREFIX". Каждая строка — отдельный счётчик,
# START_PREFIX опционален. Пример:
# YA_COUNTERS_RAW = [
#     "105003539,0bb7cf0a-ff5a-4bfe-af80-766c9492c976,utm_vlwb_",
#     "123456789,secret_token_for_second",
# ]
YA_COUNTERS_RAW: list[str] = [
    "105003539,0bb7cf0a-ff5a-4bfe-af80-766c9492c976,utm_vlwb_",
    "105003582,9f2b6831-2851-4c88-b677-a8027c435260,utm_ya_",
]


def _parse_counter_entry(entry: str) -> dict[str, str] | None:
    if not entry or not isinstance(entry, str):
        return None

    parts = [part.strip() for part in entry.split(",")]
    if len(parts) < 2:
        return None

    tid, ms = parts[0], parts[1]
    prefix = parts[2] if len(parts) > 2 else ""

    if not tid or not ms:
        return None

    return {"tid": tid, "ms": ms, "start_prefix": prefix}


YA_COUNTERS: list[dict[str, str]] = [
    parsed
    for parsed in (_parse_counter_entry(entry) for entry in YA_COUNTERS_RAW)
    if parsed
]

# Базовый endpoint для отправки данных.
YA_COLLECT_URL: str = "https://mc.yandex.ru/collect"

# Параметры просмотра страницы по умолчанию, которые «прогревают» визит перед отправкой событий.
YA_DL: str = "https://t.me/WBVLess_bot?start=mp"
YA_DR: str = "https://yandex.ru"
YA_DT: str = "Telegram Bot"

YA_EVENT_INCLUDE_DL: bool = False
YA_TIMEOUT_SECONDS: float = 10.0
YA_MAX_ATTEMPTS: int = 3
YA_RETRY_DELAY_SECONDS: float = 1.0
