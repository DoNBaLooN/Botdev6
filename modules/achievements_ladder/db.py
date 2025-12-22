from datetime import date, datetime

from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    AchvChannelJoin,
    AchvDailyLog,
    AchvNotifyLog,
    AchvProgressAnchor,
    AchvReward,
    AchvState,
)


async def reward_already_granted(session: AsyncSession, tg_id: int, steps: int) -> bool:
    res = await session.execute(select(AchvReward).where(AchvReward.tg_id == tg_id, AchvReward.steps == steps))
    return res.scalar_one_or_none() is not None


async def log_daily_visit(session: AsyncSession, tg_id: int, day: date | None = None) -> None:
    day = day or datetime.utcnow().date()
    await session.execute(
        insert(AchvDailyLog).values(tg_id=tg_id, day=day).on_conflict_do_nothing()
    )
    await session.commit()


async def monthly_daily_count(
    session: AsyncSession,
    tg_id: int,
    first_day: date,
    until_day: date | None = None,
    *,
    include_until: bool = False,
) -> int:
    query = select(func.count()).where(
        AchvDailyLog.tg_id == tg_id,
        AchvDailyLog.day >= first_day,
    )
    if until_day:
        if include_until:
            query = query.where(AchvDailyLog.day <= until_day)
        else:
            query = query.where(AchvDailyLog.day < until_day)
    res = await session.execute(query)
    return res.scalar_one()


async def has_channel_bonus(session: AsyncSession, tg_id: int) -> bool:
    return await session.get(AchvChannelJoin, tg_id) is not None


async def set_channel_bonus(session: AsyncSession, tg_id: int) -> None:
    await session.execute(insert(AchvChannelJoin).values(tg_id=tg_id).on_conflict_do_nothing())
    await session.commit()


async def get_offset(session: AsyncSession, tg_id: int) -> int:
    state = await session.get(AchvState, tg_id)
    return state.offset if state else 0


async def add_offset(session: AsyncSession, tg_id: int, delta: int) -> None:
    state = await session.get(AchvState, tg_id)
    if state:
        state.offset += delta
    else:
        state = AchvState(tg_id=tg_id, offset=delta)
        session.add(state)
    await session.commit()


async def active_users(session: AsyncSession, since: date) -> list[int]:
    res = await session.execute(
        select(AchvDailyLog.tg_id)
        .where(AchvDailyLog.day >= since)
        .group_by(AchvDailyLog.tg_id)
    )
    return [r[0] for r in res]


async def log_notification(session: AsyncSession, tg_id: int, notif_type: str) -> None:
    await session.execute(insert(AchvNotifyLog).values(tg_id=tg_id, type=notif_type))
    await session.commit()


async def last_notification(session: AsyncSession, tg_id: int, notif_type: str):
    res = await session.execute(
        select(func.max(AchvNotifyLog.sent_at)).where(
            AchvNotifyLog.tg_id == tg_id, AchvNotifyLog.type == notif_type
        )
    )
    return res.scalar_one_or_none()


async def weekly_notification_count(
    session: AsyncSession, tg_id: int, notif_type: str, since_dt: datetime
) -> int:
    res = await session.execute(
        select(func.count()).where(
            AchvNotifyLog.tg_id == tg_id,
            AchvNotifyLog.type == notif_type,
            AchvNotifyLog.sent_at >= since_dt,
        )
    )
    return res.scalar_one()


async def get_progress_anchor(session: AsyncSession, tg_id: int) -> datetime | None:
    res = await session.execute(
        select(AchvProgressAnchor.payments_since).where(AchvProgressAnchor.tg_id == tg_id)
    )
    return res.scalar_one_or_none()


async def update_progress_anchor(
    session: AsyncSession, tg_id: int, *, timestamp: datetime | None = None
) -> None:
    timestamp = timestamp or datetime.utcnow()
    await session.execute(
        insert(AchvProgressAnchor)
        .values(tg_id=tg_id, payments_since=timestamp)
        .on_conflict_do_update(
            index_elements=[AchvProgressAnchor.tg_id],
            set_={"payments_since": timestamp},
        )
    )
    await session.commit()
