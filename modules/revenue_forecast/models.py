from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Column, Date, DateTime, Index, Numeric, Text

from database.models import Base


class AdSpend(Base):
    __tablename__ = "ad_spends"
    __table_args__ = (
        Index("ix_ad_spends_month_start", "month_start"),
    )

    month_start = Column(Date, primary_key=True)
    amount_rub = Column(Numeric(14, 2), nullable=False, default=0)
    comment = Column(Text, nullable=True)
    created_by = Column(BigInteger, nullable=False)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class AdSpendSource(Base):
    __tablename__ = "ad_spends_sources"
    __table_args__ = (
        Index("ix_ad_spends_sources_month_start", "month_start"),
        Index("ix_ad_spends_sources_month_source", "month_start", "source_code", unique=True),
    )

    month_start = Column(Date, primary_key=True)
    source_code = Column(Text, primary_key=True)
    amount_rub = Column(Numeric(14, 2), nullable=False, default=0)
    comment = Column(Text, nullable=True)
    created_by = Column(BigInteger, nullable=False)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
