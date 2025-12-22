from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import YandexClientIdMap


async def upsert_cid(
    session: AsyncSession, tg_id: int, cid: str, *, counter_tid: str | None = None
) -> None:
    stmt = (
        insert(YandexClientIdMap)
        .values(
            tg_id=tg_id,
            cid=cid,
            counter_tid=counter_tid,
            created_at=datetime.utcnow(),
        )
        .on_conflict_do_update(
            index_elements=[YandexClientIdMap.tg_id],
            set_={
                "cid": cid,
                "counter_tid": counter_tid,
                "updated_at": datetime.utcnow(),
            },
        )
    )
    await session.execute(stmt)


async def get_cid(session: AsyncSession, tg_id: int) -> tuple[str | None, str | None]:
    stmt = select(YandexClientIdMap.cid, YandexClientIdMap.counter_tid).where(
        YandexClientIdMap.tg_id == tg_id
    )
    result = await session.execute(stmt)
    row = result.first()
    if row is None:
        return None, None

    return row[0], row[1]
