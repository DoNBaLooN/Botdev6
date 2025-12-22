"""Configuration for the Ruletka module."""

from __future__ import annotations
from decimal import Decimal
from os import getenv
from typing import Final

ENABLED: Final[bool] = getenv("ROULETTE_ENABLED", "true").lower() == "true"
BET_AMOUNT: Final[Decimal] = Decimal(getenv("ROULETTE_BET_AMOUNT", "25.00"))
CURRENCY_EMOJI: Final[str] = getenv("ROULETTE_CURRENCY_EMOJI", "📦")
JACKPOT_FEE: Final[Decimal] = Decimal(getenv("ROULETTE_JACKPOT_FEE", "0.12"))
BASE_JACKPOT: Final[Decimal] = Decimal(getenv("ROULETTE_BASE_JACKPOT", "300.00"))
NOTIFICATIONS_ENABLED: Final[bool] = getenv("ROULETTE_NOTIFICATIONS_ENABLED", "true").lower() == "true"
NOTIFY_ONLY_ACTIVE: Final[bool] = getenv("ROULETTE_NOTIFY_ONLY_ACTIVE", "true").lower() == "true"
ACTIVE_WINDOW_DAYS: Final[int] = int(getenv("ROULETTE_ACTIVE_WINDOW_DAYS", "7"))
SHOW_MISS_IN_LIST: Final[bool] = getenv("ROULETTE_SHOW_MISS_IN_LIST", "false").lower() == "true"
ALLOW_USER_NOTIFY_TOGGLE: Final[bool] = getenv("ROULETTE_ALLOW_USER_NOTIFY_TOGGLE", "true").lower() == "true"

RARITY_EMOJI: Final[dict[str, str]] = {
    "Легендарная": "🟣",
    "Эпическая": "🟠",
    "Редкая": "🔵",
    "Необычная": "🟢",
    "Обычная": "⚪️",
    "Проигрыш": "⚫️",
}

PRIZE_ICONS: Final[dict[str, str]] = {
    "JACKPOT": "🎰",
    "E2": "✨",
    "E200": "🏆",
    "R100": "💎",
    "U50": "🍀",
    "C10": "⭐",
    "NONE": "⚪️",
}

WHEEL_ICONS: Final[tuple[str, ...]] = (
    "🍋", "🍉", "⭐", "🔥", "💎", "🔔", "🍀", "7️⃣",
)

RARITIES: Final[list[dict[str, object]]] = [
    {"name": "Легендарная", "weight": 0.05,
     "prizes": [{"code": "JACKPOT", "title": "Джекпот", "amount": "JACKPOT", "weight": 1}]},
    {"name": "Эпическая", "weight": 1,
     "prizes": [{"code": "E200", "title": "+200 монет", "amount": 200, "weight": 1}]},
    {"name": "Редкая", "weight": 6,
     "prizes": [{"code": "R100", "title": "+100 монет", "amount": 100, "weight": 1}]},
    {"name": "Необычная", "weight": 12,
     "prizes": [{"code": "U50", "title": "+50 монет", "amount": 50, "weight": 1}]},
    {"name": "Обычная", "weight": 24,
     "prizes": [{"code": "C10", "title": "+10 монет", "amount": 10, "weight": 1}]},
    {"name": "Проигрыш", "weight": 57,
     "prizes": [{"code": "NONE", "title": "Пусто", "amount": 0, "weight": 1}]},
]

GUARANTEE_BASE: Final[int] = int(getenv("ROULETTE_GUARANTEE_BASE", "10"))
GUARANTEE_VIP: Final[int] = int(getenv("ROULETTE_GUARANTEE_VIP", "8"))
GUARANTEE_MIN_RARITY: Final[str] = getenv("ROULETTE_GUARANTEE_MIN_RARITY", "Необычная")

ANIMATION_MIN_STEPS: Final[int] = int(getenv("ROULETTE_ANIMATION_MIN_STEPS", "6"))
ANIMATION_MAX_STEPS: Final[int] = int(getenv("ROULETTE_ANIMATION_MAX_STEPS", "10"))
ANIMATION_DELAY_MS: Final[tuple[int, int]] = (
    int(getenv("ROULETTE_ANIMATION_DELAY_MIN_MS", "250")),
    int(getenv("ROULETTE_ANIMATION_DELAY_MAX_MS", "450")),
)

ANTI_SPAM_COOLDOWN_S: Final[int] = int(getenv("ROULETTE_ANTI_SPAM_COOLDOWN_S", "3"))
MAX_PARALLEL_SPINS_PER_USER: Final[int] = int(getenv("ROULETTE_MAX_PARALLEL_SPINS", "1"))
LEADERBOARD_TOP_N: Final[int] = int(getenv("ROULETTE_LEADERBOARD_TOP_N", "10"))
_LEADERBOARD_SCOPE_RAW = getenv("ROULETTE_LEADERBOARD_SCOPE", "all_time").lower()
LEADERBOARD_SCOPE: Final[str] = (
    _LEADERBOARD_SCOPE_RAW if _LEADERBOARD_SCOPE_RAW in {"all_time", "today"} else "all_time"
)

BONUS_ENABLED: Final[bool] = getenv("ROULETTE_BONUS_ENABLED", "true").lower() == "true"
BONUS_TYPE: Final[str] = getenv("ROULETTE_BONUS_TYPE", "free_spin")
BONUS_COOLDOWN_H: Final[int] = int(getenv("ROULETTE_BONUS_COOLDOWN_H", "24"))
BONUS_NOTIFY_ENABLED: Final[bool] = getenv("ROULETTE_BONUS_NOTIFY_ENABLED", "true").lower() == "true"

SEED_SECRET: Final[str] = getenv("ROULETTE_SEED_SECRET", "change-me")
WALLET_MODE: Final[str] = getenv("ROULETTE_WALLET_MODE", "db")
WALLET_ENDPOINTS: Final[dict[str, str]] = {
    "reserve": getenv("ROULETTE_WALLET_RESERVE", ""),
    "commit": getenv("ROULETTE_WALLET_COMMIT", ""),
    "rollback": getenv("ROULETTE_WALLET_ROLLBACK", ""),
}

DAILY_SPEND_LIMIT: Final[Decimal] = Decimal(getenv("ROULETTE_DAILY_SPEND_LIMIT", "0"))
DAILY_WIN_LIMIT: Final[Decimal] = Decimal(getenv("ROULETTE_DAILY_WIN_LIMIT", "0"))
JACKPOT_NOTIFY_THRESHOLD: Final[Decimal] = Decimal(getenv("ROULETTE_JACKPOT_NOTIFY_THRESHOLD", "1000"))
INACTIVE_NOTIFY_DAYS: Final[int] = int(getenv("ROULETTE_INACTIVE_NOTIFY_DAYS", "3"))
PERIODIC_JITTER_MIN_S: Final[int] = int(getenv("ROULETTE_NOTIFY_JITTER_MIN", "30"))
PERIODIC_JITTER_MAX_S: Final[int] = int(getenv("ROULETTE_NOTIFY_JITTER_MAX", "300"))

STATE_FILE: Final[str] = getenv("ROULETTE_STATE_FILE", "storage/ruletka_state.json")
JACKPOT_CACHE_TTL_S: Final[int] = int(getenv("ROULETTE_JACKPOT_CACHE_TTL_S", "3"))
PERIODIC_MAX_PER_USER: Final[int] = int(getenv("ROULETTE_NOTIFY_MAX_PER_USER", "1"))
