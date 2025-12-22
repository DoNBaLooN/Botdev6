from sqlalchemy import BigInteger, Column, DateTime, func
from database.models import Base

class SubscriptionBonus(Base):
    """Таблица для отслеживания пользователей, получивших бонус за подписку."""
    __tablename__ = 'subscription_bonus_recipients'
    
    user_id = Column(BigInteger, primary_key=True)
    received_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

