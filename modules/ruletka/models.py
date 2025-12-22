"""Database models for the Ruletka module."""

from __future__ import annotations

from datetime import datetime, date
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import UUID

from database.models import Base


class RouletteJackpot(Base):
    __tablename__ = "roulette_jackpot"

    id = Column(Integer, primary_key=True, default=1)
    amount = Column(Numeric(12, 2), nullable=False)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class RouletteUser(Base):
    __tablename__ = "roulette_users"

    tg_id = Column(BigInteger, primary_key=True)
    spins_total = Column(Integer, nullable=False, default=0)
    wins_total = Column(Integer, nullable=False, default=0)
    sum_win = Column(Numeric(12, 2), nullable=False, default=0)
    best_win = Column(Numeric(12, 2), nullable=False, default=0)
    last_jackpot_win = Column(Numeric(12, 2), nullable=True)
    streak_now = Column(Integer, nullable=False, default=0)
    streak_best = Column(Integer, nullable=False, default=0)
    guarantee_counter = Column(Integer, nullable=False, default=0)
    vip_active = Column(Boolean, nullable=False, default=False)
    bonus_next_at = Column(DateTime, nullable=True)
    free_spins = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class RoulettePreference(Base):
    __tablename__ = "roulette_prefs"

    tg_id = Column(BigInteger, ForeignKey("users.tg_id", ondelete="CASCADE"), primary_key=True)
    notify_enabled = Column(Boolean, nullable=False, default=True)
    last_spin_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class RouletteSpin(Base):
    __tablename__ = "roulette_spins"

    id = Column(Integer, primary_key=True, autoincrement=True)
    spin_id = Column(UUID(as_uuid=True), unique=True, nullable=False, default=uuid4)
    tg_id = Column(BigInteger, nullable=False, index=True)
    bet = Column(Numeric(10, 2), nullable=False)
    rarity = Column(String(32), nullable=False)
    prize_code = Column(String(32), nullable=True)
    win = Column(Numeric(12, 2), nullable=False, default=0)
    jackpot_before = Column(Numeric(12, 2), nullable=False)
    jackpot_after = Column(Numeric(12, 2), nullable=False)
    seed = Column(String(128), nullable=False)
    chat_id = Column(BigInteger, nullable=True)
    message_id = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class RouletteLeaderboardDaily(Base):
    __tablename__ = "roulette_leaderboard_daily"

    date = Column(Date, primary_key=True)
    tg_id = Column(BigInteger, ForeignKey("roulette_users.tg_id", ondelete="CASCADE"), primary_key=True)
    sum_win = Column(Numeric(12, 2), nullable=False, default=0)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


Index("ix_roulette_spins_created", RouletteSpin.created_at)
Index("ix_roulette_leaderboard_daily_sum", RouletteLeaderboardDaily.date, RouletteLeaderboardDaily.sum_win)
Index("ix_roulette_prefs_last_spin", RoulettePreference.last_spin_at)
Index("ix_roulette_users_sum_win_desc", RouletteUser.sum_win.desc())
