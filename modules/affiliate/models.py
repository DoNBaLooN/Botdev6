"""Модели SQLAlchemy для партнёрской программы."""

from __future__ import annotations

from datetime import datetime

from enum import Enum

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from database.models import Base


class AffiliateAccount(Base):
    __tablename__ = "affiliate_accounts"

    tg_id = Column(BigInteger, primary_key=True)
    ref_code = Column(String(32), unique=True, nullable=False)
    parent_l1 = Column(BigInteger, nullable=True, index=True)
    parent_l2 = Column(BigInteger, nullable=True, index=True)
    parent_l3 = Column(BigInteger, nullable=True, index=True)
    payout_method = Column(String(32), nullable=True)
    card_last4 = Column(String(4), nullable=True)
    card_encrypted = Column(LargeBinary, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    balance = relationship(
        "AffiliateBalance",
        uselist=False,
        back_populates="account",
        cascade="all, delete-orphan",
    )


class AffiliateBalance(Base):
    __tablename__ = "affiliate_balances"

    tg_id = Column(BigInteger, ForeignKey("affiliate_accounts.tg_id", ondelete="CASCADE"), primary_key=True)
    available_amount = Column(Numeric(12, 2), nullable=False, default=0)
    hold_amount = Column(Numeric(12, 2), nullable=False, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    account = relationship("AffiliateAccount", back_populates="balance")


class AffiliateTransactionType(str, Enum):
    ACCRUAL = "accrual"
    WITHDRAW_RESERVE = "withdraw_reserve"
    WITHDRAW_PAID = "withdraw_paid"
    WITHDRAW_REVERT = "withdraw_revert"


class AffiliateTransaction(Base):
    __tablename__ = "affiliate_transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tg_id = Column(BigInteger, ForeignKey("affiliate_accounts.tg_id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(32), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    ref_order_id = Column(String(64), nullable=True)
    payment_id = Column(String(128), nullable=True)
    level = Column(Integer, nullable=True)
    comment = Column(Text, nullable=True)
    hold_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AffiliateWithdrawalStatus(str, Enum):
    PENDING = "pending"
    PAID = "paid"
    REJECTED = "rejected"


class AffiliateWithdrawal(Base):
    __tablename__ = "affiliate_withdrawals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tg_id = Column(BigInteger, ForeignKey("affiliate_accounts.tg_id", ondelete="CASCADE"), nullable=False, index=True)
    amount = Column(Numeric(12, 2), nullable=False)
    status = Column(String(16), nullable=False, index=True)
    method = Column(String(32), nullable=False)
    card_snapshot_masked = Column(String(32), nullable=False)
    admin_id = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    processed_at = Column(DateTime, nullable=True)


class AffiliateEventAudit(Base):
    __tablename__ = "affiliate_events_audit"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entity = Column(String(32), nullable=False)
    entity_id = Column(String(64), nullable=False)
    actor_tg_id = Column(BigInteger, nullable=True)
    action = Column(String(64), nullable=False)
    payload_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class AffiliateReferral(Base):
    __tablename__ = "affiliate_referrals"

    user_tg_id = Column(BigInteger, primary_key=True)
    l1 = Column(BigInteger, nullable=True, index=True)
    l2 = Column(BigInteger, nullable=True, index=True)
    l3 = Column(BigInteger, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AffiliateWithdrawalReminder(Base):
    __tablename__ = "affiliate_withdrawal_notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tg_id = Column(BigInteger, nullable=False, index=True)
    action = Column(String(32), nullable=False)
    last_sent_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("tg_id", "action", name="uq_affiliate_notify_action"),
    )
