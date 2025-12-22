from datetime import datetime

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import BlockedUser, Key, ManualBan, Notification, User
from logger import logger

from .models import DiscountBroadcastState


async def get_last_sent_at(session: AsyncSession) -> datetime | None:
    state = await ensure_state(session)
    return state.last_sent_at


async def touch_last_sent_at(session: AsyncSession, when: datetime) -> None:
    stmt = (
        insert(DiscountBroadcastState)
        .values(id=1, last_sent_at=when)
        .on_conflict_do_update(
            index_elements=[DiscountBroadcastState.id],
            set_={"last_sent_at": when},
        )
    )
    await session.execute(stmt)
    await session.commit()
    logger.info(f"[DiscountsBroadcast] Метка рассылки обновлена: {when.isoformat()}")


async def fetch_target_user_ids(session: AsyncSession) -> list[int]:
    now_ms = int(datetime.utcnow().timestamp() * 1000)

    active_keys: Select = select(Key.tg_id).where(Key.expiry_time > now_ms)
    banned: Select = select(BlockedUser.tg_id).union_all(
        select(ManualBan.tg_id).where((ManualBan.until.is_(None)) | (ManualBan.until > datetime.utcnow()))
    )

    stmt = (
        select(User.tg_id)
        .distinct()
        .where(User.trial == 1)
        .where(~User.tg_id.in_(active_keys))
        .where(~User.tg_id.in_(banned))
        .where((User.is_bot.is_(False)) | (User.is_bot.is_(None)))
    )

    result = await session.execute(stmt)
    tg_ids = [row[0] for row in result.all() if row[0]]
    logger.info(f"[DiscountsBroadcast] Найдено {len(tg_ids)} получателей рассылки")
    return tg_ids


async def ensure_state(session: AsyncSession) -> DiscountBroadcastState:
    state = await session.get(DiscountBroadcastState, 1)
    if state:
        return state

    stmt = insert(DiscountBroadcastState).values(id=1, is_enabled=False, last_sent_at=None)
    await session.execute(stmt)
    await session.commit()
    state = await session.get(DiscountBroadcastState, 1)
    if state:
        logger.info("[DiscountsBroadcast] Состояние рассылки инициализировано")
        return state
    raise RuntimeError("Failed to initialize DiscountBroadcastState")


async def set_enabled(session: AsyncSession, enabled: bool) -> DiscountBroadcastState:
    stmt = (
        insert(DiscountBroadcastState)
        .values(id=1, is_enabled=enabled)
        .on_conflict_do_update(
            index_elements=[DiscountBroadcastState.id],
            set_={"is_enabled": enabled},
        )
    )
    await session.execute(stmt)
    await session.commit()
    state = await ensure_state(session)
    status = "включена" if enabled else "выключена"
    logger.info(f"[DiscountsBroadcast] Рассылка {status}")
    return state


async def activate_discount(session: AsyncSession, tg_ids: list[int], when: datetime) -> None:
    if not tg_ids:
        return

    stmt = (
        insert(Notification)
        .values(
            [
                {
                    "tg_id": tg_id,
                    "notification_type": "hot_lead_step_3",
                    "last_notification_time": when,
                }
                for tg_id in tg_ids
            ]
        )
        .on_conflict_do_update(
            index_elements=[Notification.tg_id, Notification.notification_type],
            set_={"last_notification_time": when},
        )
    )
    await session.execute(stmt)
    await session.commit()
    logger.info(
        "[DiscountsBroadcast] Активирована скидка для %d пользователей на 24 часа",
        len(tg_ids),
    )
