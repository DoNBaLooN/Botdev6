"""Настройки модуля партнёрской программы."""

from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv

# Загрузка локального .env из папки модуля
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Iterable


ENABLE_BUTTON = True

LEVEL1_PCT = Decimal("0.35")

LEVEL_PCTS: dict[int, Decimal] = {1: LEVEL1_PCT}

MIN_PAYOUT_RUB = Decimal("100")
HOLD_DAYS = 1

ADMIN_CHAT_ID = int(os.getenv("AFFILIATE_ADMIN_ID", "237563498"))  # твой Telegram ID
ADMIN_IDS = [ADMIN_CHAT_ID]  # список админов (в твоём случае — ты один)
SUPPORT_USERNAME = "vlesswbsupport_bot"

CARD_ENCRYPTION_KEY_ENV = "AFFILIATE_CARD_KEY"

USER_REMINDER_PERIOD = timedelta(days=1)
ENABLE_USER_THRESHOLD_NOTIFICATIONS = True
ADMIN_PENDING_REMINDER = timedelta(hours=6)

WITHDRAW_RATE_LIMIT = 2
WITHDRAW_RATE_LIMIT_PERIOD = timedelta(hours=24)

PAYOUT_METHOD_CARD_RU = "card_ru"
PAYOUT_METHODS = {
    PAYOUT_METHOD_CARD_RU: "Карта (RU)",
}

RU_BIN_PREFIXES: tuple[str, ...] = (
    "2200",
    "2202",
    "2204",
    "2205",
    "2207",
    "4272",
    "4276",
    "4377",
    "4584",
    "4678",
    "4744",
    "5100",
    "5128",
    "5177",
    "5204",
    "5211",
    "5484",
    "5536",
    "6762",
)

CURRENCY = "₽"

DEFAULT_PAGE_SIZE = 5

CARD_MASK_SYMBOL = "•"


@dataclass(slots=True)
class LevelPayout:
    level: int
    percent: Decimal


LEVEL_PAYOUTS: tuple[LevelPayout, ...] = tuple(LevelPayout(level=lvl, percent=pct) for lvl, pct in LEVEL_PCTS.items())
