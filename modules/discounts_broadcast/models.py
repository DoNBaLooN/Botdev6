from sqlalchemy import Boolean, Column, DateTime, Integer

from database.models import Base


class DiscountBroadcastState(Base):
    __tablename__ = "discount_broadcast_state"

    id = Column(Integer, primary_key=True, default=1)
    last_sent_at = Column(DateTime, nullable=True)
    is_enabled = Column(Boolean, nullable=False, default=False)
