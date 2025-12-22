"""DAO-методы партнёрской программы."""

from __future__ import annotations

import base64
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Iterable, Sequence

from sqlalchemy import and_, func, or_, select, update
try:  # pragma: no cover - fallback for non-PostgreSQL backends
    from sqlalchemy.dialects.postgresql import insert as pg_insert
except Exception:  # noqa: BLE001
    from sqlalchemy import insert as pg_insert  # type: ignore
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from database.models import Referral
from logger import logger

from . import settings, texts
from .models import (
    AffiliateAccount,
    AffiliateBalance,
    AffiliateEventAudit,
    AffiliateReferral,
    AffiliateTransaction,
    AffiliateWithdrawal,
    AffiliateWithdrawalReminder,
)

_DECIMAL_ZERO = Decimal("0")


@dataclass(slots=True)
class AccountSnapshot:
    account: AffiliateAccount
    balance: AffiliateBalance


@dataclass(slots=True)
class PartnerStat:
    tg_id: int
    referrals: int
    available: Decimal
    hold: Decimal


def _normalize_card(number: str) -> str:
    return "".join(ch for ch in number if ch.isdigit())


def _luhn_checksum(number: str) -> bool:
    total = 0
    reverse_digits = list(map(int, reversed(number)))
    for idx, digit in enumerate(reverse_digits):
        if idx % 2 == 1:
            doubled = digit * 2
            if doubled > 9:
                doubled -= 9
            total += doubled
        else:
            total += digit
    return total % 10 == 0


def validate_card_detailed(number: str) -> tuple[bool, str | None]:
    normalized = _normalize_card(number)
    # Оставляем только простую проверку: 16–19 цифр.
    # Без Luhn и без проверки BIN-префиксов.
    if not (16 <= len(normalized) <= 19):
        return False, texts.CARD_INVALID
    # После нормализации должны остаться только цифры (страховка от пустого ввода).
    if not normalized.isdigit():
        return False, texts.CARD_INVALID
    return True, None


def validate_card(number: str) -> bool:
    return validate_card_detailed(number)[0]


def mask_card(number: str) -> str:
    return texts.mask_card_number(number)


def _get_crypto_key() -> bytes:
    key = os.environ.get(settings.CARD_ENCRYPTION_KEY_ENV)
    if not key:
        raise RuntimeError("CARD_ENCRYPTION_KEY is not configured")
    key_bytes: bytes
    try:
        key_bytes = base64.urlsafe_b64decode(key)
        if len(key_bytes) not in (16, 24, 32):
            raise ValueError
    except Exception:
        # fallback to deriving from raw string
        key_bytes = key.encode()
    if len(key_bytes) not in (16, 24, 32):
        # pad or trim via hashing
        import hashlib

        key_bytes = hashlib.sha256(key_bytes).digest()
    return key_bytes[:32]


def encrypt_card(number: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    aes = AESGCM(_get_crypto_key())
    nonce = secrets.token_bytes(12)
    ciphertext = aes.encrypt(nonce, number.encode(), None)
    return nonce + ciphertext


def decrypt_card(blob: bytes) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if not blob:
        return ""
    aes = AESGCM(_get_crypto_key())
    nonce, cipher = blob[:12], blob[12:]
    plain = aes.decrypt(nonce, cipher, None)
    return plain.decode()


async def log_event(
    session: AsyncSession,
    *,
    entity: str,
    entity_id: str,
    actor_tg_id: int | None,
    action: str,
    payload: dict | None = None,
) -> None:
    audit = AffiliateEventAudit(
        entity=entity,
        entity_id=entity_id,
        actor_tg_id=actor_tg_id,
        action=action,
        payload_json=payload,
    )
    session.add(audit)


async def _generate_ref_code(session: AsyncSession) -> str:
    while True:
        code = secrets.token_urlsafe(6).replace("-", "").replace("_", "").lower()
        if len(code) < 6:
            code = f"{code}{secrets.token_hex(3)}"
        existing = await session.execute(select(AffiliateAccount).where(AffiliateAccount.ref_code == code))
        if not existing.scalar_one_or_none():
            return code[:16]


async def _resolve_tree(session: AsyncSession, tg_id: int) -> tuple[int | None, int | None, int | None]:
    level_1 = await session.execute(select(Referral.referrer_tg_id).where(Referral.referred_tg_id == tg_id))
    l1 = level_1.scalar_one_or_none()
    l2 = None
    l3 = None
    if l1:
        second = await session.execute(select(Referral.referrer_tg_id).where(Referral.referred_tg_id == l1))
        l2 = second.scalar_one_or_none()
        if l2:
            third = await session.execute(select(Referral.referrer_tg_id).where(Referral.referred_tg_id == l2))
            l3 = third.scalar_one_or_none()
    return l1, l2, l3


async def get_parent_chain(session: AsyncSession, tg_id: int) -> tuple[int | None, int | None, int | None]:
    return await _resolve_tree(session, tg_id)


async def ensure_account(session: AsyncSession, tg_id: int) -> AccountSnapshot:
    created = False
    balance_created = False
    query = (
        select(AffiliateAccount)
        .options(joinedload(AffiliateAccount.balance))
        .where(AffiliateAccount.tg_id == tg_id)
    )
    result = await session.execute(query)
    account = result.scalar_one_or_none()
    if account:
        if not account.balance:
            balance = AffiliateBalance(tg_id=tg_id)
            session.add(balance)
            account.balance = balance
            balance_created = True
        snapshot = AccountSnapshot(account=account, balance=account.balance)
    else:
        created = True
        ref_code = await _generate_ref_code(session)
        parent_l1, parent_l2, parent_l3 = await _resolve_tree(session, tg_id)
        account = AffiliateAccount(
            tg_id=tg_id,
            ref_code=ref_code,
            parent_l1=parent_l1,
            parent_l2=parent_l2,
            parent_l3=parent_l3,
        )
        session.add(account)
        balance = AffiliateBalance(tg_id=tg_id)
        session.add(balance)
        session.add(
            AffiliateReferral(
                user_tg_id=tg_id,
                l1=parent_l1,
                l2=parent_l2,
                l3=parent_l3,
            )
        )
        await log_event(
            session,
            entity="account",
            entity_id=str(tg_id),
            actor_tg_id=tg_id,
            action="created",
            payload={"parent_l1": parent_l1, "parent_l2": parent_l2, "parent_l3": parent_l3},
        )
        snapshot = AccountSnapshot(account=account, balance=balance)
    if created or balance_created:
        await session.flush()
        await session.commit()
        await session.refresh(snapshot.account)
        await session.refresh(snapshot.balance)
    return snapshot


async def refresh_tree(session: AsyncSession, tg_id: int) -> None:
    parents = await _resolve_tree(session, tg_id)
    query = select(AffiliateAccount).where(AffiliateAccount.tg_id == tg_id)
    result = await session.execute(query)
    account = result.scalar_one_or_none()
    if account:
        account.parent_l1, account.parent_l2, account.parent_l3 = parents
        account.updated_at = datetime.utcnow()
    else:
        await ensure_account(session, tg_id)
    stmt = pg_insert(AffiliateReferral).values(
        user_tg_id=tg_id,
        l1=parents[0],
        l2=parents[1],
        l3=parents[2],
        created_at=datetime.utcnow(),
    )
    if hasattr(stmt, "on_conflict_do_update"):
        update_stmt = stmt.on_conflict_do_update(
            index_elements=[AffiliateReferral.user_tg_id],
            set_={"l1": parents[0], "l2": parents[1], "l3": parents[2]},
        )
        await session.execute(update_stmt)
    else:  # fallback for engines без UPSERT
        existing = await session.execute(
            select(AffiliateReferral).where(AffiliateReferral.user_tg_id == tg_id)
        )
        if existing.scalar_one_or_none():
            await session.execute(
                update(AffiliateReferral)
                    .where(AffiliateReferral.user_tg_id == tg_id)
                    .values(l1=parents[0], l2=parents[1], l3=parents[2])
            )
        else:
            session.add(
                AffiliateReferral(
                    user_tg_id=tg_id,
                    l1=parents[0],
                    l2=parents[1],
                    l3=parents[2],
                )
            )


async def get_account_by_code(session: AsyncSession, code: str) -> AffiliateAccount | None:
    query = (
        select(AffiliateAccount)
        .options(joinedload(AffiliateAccount.balance))
        .where(AffiliateAccount.ref_code == code)
    )
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def update_card(
    session: AsyncSession,
    *,
    tg_id: int,
    card_number: str,
    actor: int,
) -> AccountSnapshot:
    normalized = _normalize_card(card_number)
    snapshot = await ensure_account(session, tg_id)
    masked = mask_card(normalized)
    encrypted = encrypt_card(normalized)

    account = snapshot.account
    if account.card_last4 == normalized[-4:]:
        raise ValueError(texts.CARD_SAME_AS_CURRENT)

    account.card_last4 = normalized[-4:]
    account.card_encrypted = encrypted
    account.payout_method = settings.PAYOUT_METHOD_CARD_RU
    account.updated_at = datetime.utcnow()
    await log_event(
        session,
        entity="payout_method",
        entity_id=str(tg_id),
        actor_tg_id=actor,
        action="card_saved",
        payload={"masked": masked},
    )
    return snapshot


async def remove_card(session: AsyncSession, *, tg_id: int, actor: int) -> None:
    snapshot = await ensure_account(session, tg_id)
    account = snapshot.account
    account.card_last4 = None
    account.card_encrypted = None
    account.payout_method = None
    account.updated_at = datetime.utcnow()
    await log_event(
        session,
        entity="payout_method",
        entity_id=str(tg_id),
        actor_tg_id=actor,
        action="card_deleted",
        payload=None,
    )


async def get_account(session: AsyncSession, tg_id: int) -> AccountSnapshot:
    snapshot = await ensure_account(session, tg_id)
    return snapshot


async def get_stats(session: AsyncSession, tg_id: int) -> dict:
    from database.referrals import get_referral_stats

    stats = await get_referral_stats(session, tg_id)
    total = stats.get("total_referrals", 0)
    return {"invited": total, "levels": stats.get("referrals_by_level", {})}


async def accrue_reward(
    session: AsyncSession,
    *,
    tg_id: int,
    amount: Decimal,
    level: int | None,
    payment_id: str | None,
    ref_order_id: str | None,
    hold_until: datetime | None,
    comment: str | None = None,
) -> None:
    snapshot = await ensure_account(session, tg_id)
    balance = snapshot.balance
    account = snapshot.account

    txn = AffiliateTransaction(
        tg_id=tg_id,
        type="accrual",
        amount=amount.quantize(Decimal("0.01")),
        level=level,
        payment_id=payment_id,
        ref_order_id=ref_order_id,
        comment=comment,
        hold_until=hold_until,
    )
    session.add(txn)
    now = datetime.utcnow()
    if hold_until and hold_until > now:
        balance.hold_amount = (Decimal(balance.hold_amount or 0) + amount).quantize(Decimal("0.01"))
    else:
        balance.available_amount = (Decimal(balance.available_amount or 0) + amount).quantize(Decimal("0.01"))
    balance.updated_at = now
    account.updated_at = now
    await session.flush()
    await log_event(
        session,
        entity="transaction",
        entity_id=str(txn.id),
        actor_tg_id=tg_id,
        action="accrual_created",
        payload={"amount": float(amount), "level": level, "hold_until": hold_until.isoformat() if hold_until else None},
    )


async def release_accruals(session: AsyncSession, *, now: datetime | None = None) -> list[tuple[int, Decimal]]:
    now = now or datetime.utcnow()
    query = select(AffiliateTransaction).where(
        AffiliateTransaction.type == "accrual",
        AffiliateTransaction.hold_until.isnot(None),
        AffiliateTransaction.hold_until <= now,
    )
    result = await session.execute(query)
    transactions: Sequence[AffiliateTransaction] = result.scalars().all()
    released: list[tuple[int, Decimal]] = []
    for txn in transactions:
        balance_query = select(AffiliateBalance).where(AffiliateBalance.tg_id == txn.tg_id)
        balance_result = await session.execute(balance_query)
        balance = balance_result.scalar_one_or_none()
        if not balance:
            continue
        amount = Decimal(txn.amount or 0)
        balance.available_amount = (Decimal(balance.available_amount or 0) + amount).quantize(Decimal("0.01"))
        balance.hold_amount = max(_DECIMAL_ZERO, (Decimal(balance.hold_amount or 0) - amount)).quantize(Decimal("0.01"))
        balance.updated_at = now
        txn.hold_until = None
        released.append((txn.tg_id, amount))
    return released


async def get_balance(session: AsyncSession, tg_id: int) -> AffiliateBalance:
    snapshot = await ensure_account(session, tg_id)
    return snapshot.balance


async def get_pending_withdrawal(session: AsyncSession, tg_id: int) -> AffiliateWithdrawal | None:
    query = select(AffiliateWithdrawal).where(
        AffiliateWithdrawal.tg_id == tg_id,
        AffiliateWithdrawal.status == "pending",
    )
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def check_withdraw_rate_limit(session: AsyncSession, tg_id: int) -> bool:
    if settings.WITHDRAW_RATE_LIMIT <= 0:
        return True
    since = datetime.utcnow() - settings.WITHDRAW_RATE_LIMIT_PERIOD
    query = select(func.count()).select_from(AffiliateWithdrawal).where(
        AffiliateWithdrawal.tg_id == tg_id,
        AffiliateWithdrawal.created_at >= since,
    )
    result = await session.execute(query)
    count = result.scalar_one_or_none() or 0
    return count < settings.WITHDRAW_RATE_LIMIT


async def create_withdrawal(
    session: AsyncSession,
    *,
    tg_id: int,
    amount: Decimal,
    method: str,
    card_snapshot: str,
    actor: int,
) -> AffiliateWithdrawal:
    balance = await get_balance(session, tg_id)
    amount = amount.quantize(Decimal("0.01"))
    available = Decimal(balance.available_amount or 0)
    if available < amount:
        raise ValueError("insufficient")
    balance.available_amount = (available - amount).quantize(Decimal("0.01"))
    balance.hold_amount = (Decimal(balance.hold_amount or 0) + amount).quantize(Decimal("0.01"))
    balance.updated_at = datetime.utcnow()

    withdrawal = AffiliateWithdrawal(
        tg_id=tg_id,
        amount=amount,
        status="pending",
        method=method,
        card_snapshot_masked=card_snapshot,
    )
    session.add(withdrawal)

    txn = AffiliateTransaction(
        tg_id=tg_id,
        type="withdraw_reserve",
        amount=-amount,
        comment="reserve",
    )
    session.add(txn)
    await session.flush()

    await log_event(
        session,
        entity="withdrawal",
        entity_id=str(withdrawal.id),
        actor_tg_id=actor,
        action="created",
        payload={"amount": float(amount), "method": method},
    )
    return withdrawal


async def set_withdrawal_status(
    session: AsyncSession,
    *,
    withdrawal_id: int,
    status: str,
    admin_id: int,
) -> AffiliateWithdrawal | None:
    query = select(AffiliateWithdrawal).where(AffiliateWithdrawal.id == withdrawal_id)
    result = await session.execute(query)
    withdrawal = result.scalar_one_or_none()
    if not withdrawal:
        return None
    if withdrawal.status != "pending":
        return withdrawal

    withdrawal.status = status
    withdrawal.admin_id = admin_id
    withdrawal.processed_at = datetime.utcnow()

    balance = await get_balance(session, withdrawal.tg_id)
    amount = Decimal(withdrawal.amount or 0)
    if status == "paid":
        balance.hold_amount = max(_DECIMAL_ZERO, (Decimal(balance.hold_amount or 0) - amount)).quantize(Decimal("0.01"))
        txn = AffiliateTransaction(
            tg_id=withdrawal.tg_id,
            type="withdraw_paid",
            amount=_DECIMAL_ZERO,
            comment=f"withdrawal:{withdrawal.id}",
        )
        session.add(txn)
    elif status == "rejected":
        balance.hold_amount = max(_DECIMAL_ZERO, (Decimal(balance.hold_amount or 0) - amount)).quantize(Decimal("0.01"))
        balance.available_amount = (Decimal(balance.available_amount or 0) + amount).quantize(Decimal("0.01"))
        txn = AffiliateTransaction(
            tg_id=withdrawal.tg_id,
            type="withdraw_revert",
            amount=amount,
            comment=f"withdrawal:{withdrawal.id}",
        )
        session.add(txn)
    balance.updated_at = datetime.utcnow()

    await log_event(
        session,
        entity="withdrawal",
        entity_id=str(withdrawal.id),
        actor_tg_id=admin_id,
        action=status,
        payload={"amount": float(amount)},
    )
    return withdrawal


async def list_withdrawals(
    session: AsyncSession,
    *,
    status: str | None,
    since: datetime | None,
    tg_id: int | None,
    page: int,
    page_size: int,
) -> tuple[list[AffiliateWithdrawal], int]:
    conditions = []
    if status and status != "all":
        conditions.append(AffiliateWithdrawal.status == status)
    if since:
        conditions.append(AffiliateWithdrawal.created_at >= since)
    if tg_id:
        conditions.append(AffiliateWithdrawal.tg_id == tg_id)
    query = select(AffiliateWithdrawal).order_by(AffiliateWithdrawal.created_at.desc())
    if conditions:
        query = query.where(and_(*conditions))
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await session.execute(count_query)
    total = total_result.scalar_one_or_none() or 0

    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(query)
    return result.scalars().all(), total


async def get_balance_map(session: AsyncSession, tg_ids: Iterable[int]) -> dict[int, AffiliateBalance]:
    if not tg_ids:
        return {}
    query = select(AffiliateBalance).where(AffiliateBalance.tg_id.in_(list(tg_ids)))
    result = await session.execute(query)
    return {row.tg_id: row for row in result.scalars().all()}


async def list_partner_stats(
    session: AsyncSession,
    *,
    page: int,
    page_size: int,
) -> tuple[list[PartnerStat], int, int]:
    page = max(1, page)
    page_size = max(1, page_size)
    balance_subq = (
        select(
            AffiliateBalance.tg_id.label("tg_id"),
            AffiliateBalance.available_amount.label("available"),
            AffiliateBalance.hold_amount.label("hold"),
        )
        .subquery()
    )
    count_referrals = func.count(Referral.referred_tg_id)
    available_amount = func.coalesce(balance_subq.c.available, 0)
    hold_amount = func.coalesce(balance_subq.c.hold, 0)

    base_query = (
        select(
            AffiliateAccount.tg_id.label("tg_id"),
            count_referrals.label("referrals"),
            available_amount.label("available"),
            hold_amount.label("hold"),
        )
        .select_from(AffiliateAccount)
        .join(balance_subq, balance_subq.c.tg_id == AffiliateAccount.tg_id, isouter=True)
        .join(Referral, Referral.referrer_tg_id == AffiliateAccount.tg_id, isouter=True)
        .group_by(AffiliateAccount.tg_id, balance_subq.c.available, balance_subq.c.hold)
        .having(
            or_(
                count_referrals > 0,
                available_amount + hold_amount > 0,
            )
        )
        .order_by(count_referrals.desc(), AffiliateAccount.tg_id.asc())
    )

    stats_subq = base_query.subquery()
    total_result = await session.execute(select(func.count()).select_from(stats_subq))
    total = total_result.scalar_one_or_none() or 0

    if total == 0:
        return [], 0, 1

    total_pages = max(1, (total + page_size - 1) // page_size)
    current_page = min(page, total_pages)
    offset = (current_page - 1) * page_size

    result = await session.execute(select(stats_subq).offset(offset).limit(page_size))
    rows = result.mappings().all()

    stats = [
        PartnerStat(
            tg_id=int(row["tg_id"]),
            referrals=int(row["referrals"] or 0),
            available=Decimal(row["available"] or 0),
            hold=Decimal(row["hold"] or 0),
        )
        for row in rows
    ]

    return stats, total, current_page


async def get_pending_for_admin_reminder(session: AsyncSession, *, older_than: timedelta) -> list[AffiliateWithdrawal]:
    threshold = datetime.utcnow() - older_than
    query = select(AffiliateWithdrawal).where(
        AffiliateWithdrawal.status == "pending",
        AffiliateWithdrawal.created_at <= threshold,
    ).order_by(AffiliateWithdrawal.created_at.asc())
    result = await session.execute(query)
    return result.scalars().all()


async def mark_notification(session: AsyncSession, *, tg_id: int, action: str) -> None:
    now = datetime.utcnow()
    stmt = pg_insert(AffiliateWithdrawalReminder).values(
        tg_id=tg_id,
        action=action,
        last_sent_at=now,
    )
    if hasattr(stmt, "on_conflict_do_update"):
        update_stmt = stmt.on_conflict_do_update(
            index_elements=[AffiliateWithdrawalReminder.tg_id, AffiliateWithdrawalReminder.action],
            set_={"last_sent_at": now},
        )
        await session.execute(update_stmt)
    else:
        existing = await session.execute(
            select(AffiliateWithdrawalReminder).where(
                AffiliateWithdrawalReminder.tg_id == tg_id,
                AffiliateWithdrawalReminder.action == action,
            )
        )
        if existing.scalar_one_or_none():
            await session.execute(
                update(AffiliateWithdrawalReminder)
                .where(
                    AffiliateWithdrawalReminder.tg_id == tg_id,
                    AffiliateWithdrawalReminder.action == action,
                )
                .values(last_sent_at=now)
            )
        else:
            session.add(
                AffiliateWithdrawalReminder(
                    tg_id=tg_id,
                    action=action,
                    last_sent_at=now,
                )
            )


async def can_notify(session: AsyncSession, *, tg_id: int, action: str, period: timedelta) -> bool:
    query = select(AffiliateWithdrawalReminder).where(
        AffiliateWithdrawalReminder.tg_id == tg_id,
        AffiliateWithdrawalReminder.action == action,
    )
    result = await session.execute(query)
    record = result.scalar_one_or_none()
    if not record:
        return True
    return record.last_sent_at + period <= datetime.utcnow()


async def get_ref_link(tg_id: int, account: AffiliateAccount) -> str:
    from config import USERNAME_BOT

    return f"https://t.me/{USERNAME_BOT}?start=affiliate_{account.ref_code}"
