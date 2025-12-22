from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Key, Tariff


async def user_is_trial(session: AsyncSession, tg_id: int, trial_id: int) -> bool:
    """
    True, если у пользователя (tg_id) есть ХОТЯ БЫ ОДИН активный (не замороженный, не просроченный)
    ключ с тарифом trial_name.
    """
    now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    q = (
        select(1)
        .select_from(Key)
        .join(Tariff, Tariff.id == Key.tariff_id)
        .where(
            Key.tg_id == tg_id,
            Key.is_frozen.is_(False),
            Key.expiry_time > now_ms,
            Tariff.id == trial_id,
        )
        .limit(1)
    )
    res = await session.execute(q)
    return res.scalar_one_or_none() is not None


async def key_is_trial(session: AsyncSession, key_name: str, trial_id: int) -> bool:
    """
    True, если у указанного текстового имени ключа (колонка keys.key) активный тариф trial_name.
    """
    if not key_name:
        return False
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    q = (
        select(1)
        .select_from(Key)
        .join(Tariff, Tariff.id == Key.tariff_id)
        .where(
            Key.key == key_name,      # в схеме колонка называется "key"
            Key.is_frozen.is_(False),
            Key.expiry_time > now_ms,
            Tariff.id == trial_id,
        )
        .limit(1)
    )
    res = await session.execute(q)
    return res.scalar_one_or_none() is not None


async def client_is_trial(session: AsyncSession, tg_id: int, client_id: str, trial_id: int) -> bool:
    """
    True, если у пользователя (tg_id) и конкретного client_id есть активный ключ с тарифом trial_name.
    Удобно, когда меню оплаты открывается для данного клиента.
    """
    if not client_id:
        return False
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    q = (
        select(1)
        .select_from(Key)
        .join(Tariff, Tariff.id == Key.tariff_id)
        .where(
            Key.tg_id == tg_id,
            Key.client_id == client_id,
            Key.is_frozen.is_(False),
            Key.expiry_time > now_ms,
            Tariff.name == trial_name,
        )
        .limit(1)
    )
    res = await session.execute(q)
    return res.scalar_one_or_none() is not None
