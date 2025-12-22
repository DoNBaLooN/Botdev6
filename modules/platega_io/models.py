from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Float, Integer, String
from sqlalchemy.orm import declarative_base


ModuleBase = declarative_base()


class PendingPayment(ModuleBase):
    __tablename__ = "platega_pending_payments"

    external_id = Column(String, primary_key=True)
    tg_id = Column(BigInteger, nullable=False)
    amount = Column(Float, nullable=True)
    payment_system = Column(String, default="platega")
    method_code = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


