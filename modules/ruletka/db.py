"""Database helpers for the roulette module."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Sequence
from uuid import UUID

from sqlalchemy import Select, func, literal, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User

from . import settings
from .state import state as module_state
from .models import (
    RouletteJackpot,
    RouletteLeaderboardDaily,
    RoulettePreference,
    RouletteSpin,
    RouletteUser,
)


TWO_PLACES = Decimal("0.01")


def _to_decimal(value: Decimal | float | int | str) -> Decimal:
    if isinstance(value, Decimal):
        dec = value
    else:
        dec = Decimal(str(value))
    return dec.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


@dataclass(slots=True)
class SpinRecord:
    spin_id: UUID
    tg_id: int
    bet: Decimal
    win: Decimal
    rarity: str
    prize_code: str | None
    seed: str
    jackpot_before: Decimal
    jackpot_after: Decimal
    chat_id: int | None
    message_id: int | None
    created_at: datetime


class JackpotDAO:
    """Helpers for interacting with the jackpot state."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ensure(self, *, for_update: bool = False) -> RouletteJackpot:
        if for_update:
            stmt = select(RouletteJackpot).where(RouletteJackpot.id == 1).with_for_update()
            result = await self._session.execute(stmt)
            jackpot = result.scalar_one_or_none()
            if jackpot is None:
                jackpot = RouletteJackpot(id=1, amount=_to_decimal(module_state.base_jackpot))
                self._session.add(jackpot)
                await self._session.flush()
            return jackpot
        jackpot = await self._session.get(RouletteJackpot, 1)
        if jackpot is None:
            jackpot = RouletteJackpot(id=1, amount=_to_decimal(module_state.base_jackpot))
            self._session.add(jackpot)
            await self._session.flush()
        return jackpot

    async def get_amount(self) -> Decimal:
        jackpot = await self.ensure()
        return _to_decimal(jackpot.amount or module_state.base_jackpot)


class RouletteUserDAO:
    """Helpers for roulette-specific user stats."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create(self, tg_id: int) -> RouletteUser:
        user = await self._session.get(RouletteUser, tg_id)
        if user is None:
            user = RouletteUser(tg_id=tg_id)
            self._session.add(user)
            await self._session.flush()
        return user

    async def set_vip(self, tg_id: int, value: bool) -> None:
        user = await self.get_or_create(tg_id)
        user.vip_active = value
        user.updated_at = datetime.utcnow()
        await self._session.flush()

    async def increment_spin(
        self,
        tg_id: int,
        *,
        win_amount: Decimal,
        jackpot_win: bool,
        non_empty_prize: bool,
    ) -> RouletteUser:
        user = await self.get_or_create(tg_id)
        user.spins_total += 1
        if win_amount > 0:
            user.wins_total += 1
            user.sum_win = _to_decimal((user.sum_win or 0) + win_amount)
            if win_amount > (user.best_win or Decimal("0")):
                user.best_win = win_amount
            user.streak_now += 1
            if user.streak_now > user.streak_best:
                user.streak_best = user.streak_now
        else:
            user.streak_now = 0

        if jackpot_win:
            user.last_jackpot_win = win_amount

        if non_empty_prize:
            user.guarantee_counter = 0
        else:
            user.guarantee_counter += 1

        user.updated_at = datetime.utcnow()
        await self._session.flush()
        return user

    async def update_bonus_next(self, tg_id: int, *, next_at: datetime | None) -> RouletteUser:
        user = await self.get_or_create(tg_id)
        user.bonus_next_at = next_at
        user.updated_at = datetime.utcnow()
        await self._session.flush()
        return user

    async def adjust_free_spins(self, tg_id: int, delta: int) -> RouletteUser:
        user = await self.get_or_create(tg_id)
        user.free_spins = max(0, (user.free_spins or 0) + delta)
        user.updated_at = datetime.utcnow()
        await self._session.flush()
        return user

    async def get_free_spins(self, tg_id: int) -> int:
        user = await self.get_or_create(tg_id)
        return int(user.free_spins or 0)


class BonusDAO:
    """Bonus specific helpers."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._user_dao = RouletteUserDAO(session)

    async def get_next_at(self, tg_id: int) -> datetime | None:
        user = await self._user_dao.get_or_create(tg_id)
        return user.bonus_next_at

    async def set_next_at(self, tg_id: int, *, next_at: datetime | None) -> None:
        await self._user_dao.update_bonus_next(tg_id, next_at=next_at)


class LeaderboardDAO:
    """Helpers for the daily leaderboard."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_win(self, *, tg_id: int, amount: Decimal, day: date) -> None:
        if amount <= 0:
            return
        stmt = insert(RouletteLeaderboardDaily).values(
            date=day,
            tg_id=tg_id,
            sum_win=amount,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[RouletteLeaderboardDaily.date, RouletteLeaderboardDaily.tg_id],
            set_={
                "sum_win": RouletteLeaderboardDaily.sum_win + literal(amount),
                "updated_at": func.now(),
            },
        )
        await self._session.execute(stmt)

    async def fetch_top(self, *, day: date, limit: int) -> Sequence[tuple[int, Decimal]]:
        stmt: Select = (
            select(RouletteLeaderboardDaily.tg_id, RouletteLeaderboardDaily.sum_win)
            .where(RouletteLeaderboardDaily.date == day)
            .order_by(RouletteLeaderboardDaily.sum_win.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        rows = result.all()
        return [(row[0], _to_decimal(row[1])) for row in rows]

    async def fetch_top_all_time(self, *, limit: int) -> Sequence[tuple[int, Decimal]]:
        stmt: Select = (
            select(RouletteUser.tg_id, RouletteUser.sum_win)
            .order_by(RouletteUser.sum_win.desc(), RouletteUser.tg_id.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        rows = result.all()
        return [(row[0], _to_decimal(row[1])) for row in rows]

    async def get_user_position(self, *, tg_id: int, day: date) -> tuple[int | None, Decimal]:
        target_sum = (
            select(RouletteLeaderboardDaily.sum_win)
            .where(
                (RouletteLeaderboardDaily.date == day)
                & (RouletteLeaderboardDaily.tg_id == tg_id)
            )
            .limit(1)
            .scalar_subquery()
        )
        total_stmt = select(target_sum)
        total_result = await self._session.execute(total_stmt)
        total = total_result.scalar_one_or_none()
        if total is None:
            return None, Decimal("0")
        stmt = (
            select(func.count())
            .where(
                (RouletteLeaderboardDaily.date == day)
                & (RouletteLeaderboardDaily.sum_win > target_sum)
            )
        )
        result = await self._session.execute(stmt)
        higher = result.scalar_one()
        return higher + 1, _to_decimal(total)

    async def get_user_position_all_time(self, *, tg_id: int) -> tuple[int | None, Decimal]:
        target_sum = (
            select(RouletteUser.sum_win)
            .where(RouletteUser.tg_id == tg_id)
            .limit(1)
            .scalar_subquery()
        )
        total_stmt = select(target_sum)
        total_result = await self._session.execute(total_stmt)
        total = total_result.scalar_one_or_none()
        if total is None:
            return None, Decimal("0")
        stmt = select(func.count()).where(RouletteUser.sum_win > target_sum)
        result = await self._session.execute(stmt)
        higher = result.scalar_one()
        return higher + 1, _to_decimal(total)


async def get_user_balance(session: AsyncSession, tg_id: int, *, for_update: bool = False) -> Decimal:
    stmt = select(func.coalesce(User.balance, 0.0)).where(User.tg_id == tg_id)
    if for_update:
        stmt = stmt.with_for_update()
    result = await session.execute(stmt)
    value = result.scalar_one_or_none()
    if value is None:
        raise ValueError(f"User {tg_id} not found")
    return _to_decimal(value)


async def change_user_balance(session: AsyncSession, tg_id: int, delta: Decimal) -> Decimal:
    stmt = select(User).where(User.tg_id == tg_id).with_for_update()
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError(f"User {tg_id} not found")
    current = Decimal(str(user.balance or 0))
    new_balance = _to_decimal(current + delta)
    user.balance = float(new_balance)
    await session.flush()
    return new_balance


async def get_notify_enabled(session: AsyncSession, tg_id: int) -> bool:
    pref = await session.get(RoulettePreference, tg_id)
    if pref is None:
        pref = RoulettePreference(tg_id=tg_id)
        session.add(pref)
        await session.flush()
    return bool(pref.notify_enabled)


async def set_notify_enabled(session: AsyncSession, tg_id: int, enabled: bool) -> None:
    pref = await session.get(RoulettePreference, tg_id)
    now = datetime.utcnow()
    if pref is None:
        pref = RoulettePreference(tg_id=tg_id, notify_enabled=enabled, updated_at=now)
        session.add(pref)
    else:
        pref.notify_enabled = enabled
        pref.updated_at = now
    await session.flush()


async def touch_last_spin(session: AsyncSession, tg_id: int, *, when: datetime | None = None) -> None:
    pref = await session.get(RoulettePreference, tg_id)
    timestamp = when or datetime.utcnow()
    if pref is None:
        pref = RoulettePreference(tg_id=tg_id, last_spin_at=timestamp)
        session.add(pref)
    else:
        pref.last_spin_at = timestamp
        pref.updated_at = datetime.utcnow()
    await session.flush()


async def record_spin(session: AsyncSession, record: SpinRecord) -> RouletteSpin:
    spin = RouletteSpin(
        spin_id=record.spin_id,
        tg_id=record.tg_id,
        bet=record.bet,
        win=record.win,
        rarity=record.rarity,
        prize_code=record.prize_code,
        seed=record.seed,
        jackpot_before=record.jackpot_before,
        jackpot_after=record.jackpot_after,
        chat_id=record.chat_id,
        message_id=record.message_id,
        created_at=record.created_at,
    )
    session.add(spin)
    await session.flush()
    return spin


async def get_daily_totals(session: AsyncSession, *, tg_id: int, day: date) -> tuple[Decimal, Decimal]:
    stmt = (
        select(
            func.coalesce(func.sum(RouletteSpin.bet), 0),
            func.coalesce(func.sum(RouletteSpin.win), 0),
        )
        .where(
            (RouletteSpin.tg_id == tg_id)
            & (func.date(RouletteSpin.created_at) == day)
        )
    )
    result = await session.execute(stmt)
    spent, won = result.one()
    return _to_decimal(spent), _to_decimal(won)


async def fetch_recent_spins(
    session: AsyncSession,
    *,
    tg_id: int,
    limit: int = 10,
) -> Sequence[RouletteSpin]:
    stmt = (
        select(RouletteSpin)
        .where(RouletteSpin.tg_id == tg_id)
        .order_by(RouletteSpin.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def load_last_spins(session: AsyncSession, limit: int = 50) -> Sequence[RouletteSpin]:
    stmt = select(RouletteSpin).order_by(RouletteSpin.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    return result.scalars().all()


async def count_winning_days(session: AsyncSession, *, tg_id: int) -> int:
    stmt = (
        select(func.count(func.distinct(func.date(RouletteSpin.created_at))))
        .where((RouletteSpin.tg_id == tg_id) & (RouletteSpin.win > 0))
    )
    result = await session.execute(stmt)
    return int(result.scalar_one_or_none() or 0)


async def get_active_users(session: AsyncSession, since_ts: datetime) -> Iterable[int]:
    prefs_stmt = select(RoulettePreference.tg_id).where(
        (RoulettePreference.last_spin_at.is_not(None))
        & (RoulettePreference.last_spin_at >= since_ts)
    )
    pref_result = await session.execute(prefs_stmt)
    active_ids: set[int] = {row[0] for row in pref_result.all() if row[0] is not None}

    spins_stmt = select(func.distinct(RouletteSpin.tg_id)).where(
        RouletteSpin.created_at >= since_ts
    )
    spin_result = await session.execute(spins_stmt)
    active_ids.update(row[0] for row in spin_result.all() if row[0] is not None)

    return active_ids
