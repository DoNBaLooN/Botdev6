from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Key
from handlers.keys.operations import renew_key_in_cluster
from logger import logger

from .models import MaintenanceAttempt


async def add_attempt(session: AsyncSession, tg_id: int) -> None:
    stmt = (
        insert(MaintenanceAttempt)
        .values(tg_id=tg_id, attempted_at=datetime.utcnow())
        .on_conflict_do_update(
            index_elements=[MaintenanceAttempt.tg_id],
            set_={"attempted_at": datetime.utcnow()},
        )
    )
    await session.execute(stmt)
    await session.commit()


async def get_attempted_users(session: AsyncSession) -> list[int]:
    res = await session.execute(select(MaintenanceAttempt.tg_id))
    return [row[0] for row in res.all()]


async def clear_attempts(session: AsyncSession, tg_ids: list[int]) -> None:
    if not tg_ids:
        return
    await session.execute(delete(MaintenanceAttempt).where(MaintenanceAttempt.tg_id.in_(tg_ids)))
    await session.commit()


async def add_day_subscription(session: AsyncSession, tg_id: int) -> None:
    """Extend all user's keys by one day and sync panels."""
    res = await session.execute(select(Key).where(Key.tg_id == tg_id))
    keys = res.scalars().all()
    if not keys:
        return
    for key in keys:
        new_expiry = key.expiry_time + 86_400_000
        try:
            await renew_key_in_cluster(
                cluster_id=key.server_id,
                email=key.email,
                client_id=key.client_id,
                new_expiry_time=int(new_expiry),
                total_gb=0,
                session=session,
                reset_traffic=False,
            )
            await session.execute(update(Key).where(Key.client_id == key.client_id).values(expiry_time=new_expiry))
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to extend key %s: %s", key.client_id, e)
    await session.commit()
