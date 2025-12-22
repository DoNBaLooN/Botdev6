from datetime import datetime

from sqlalchemy import BigInteger, Column, Date, DateTime, Integer, String

from database.models import Base


class AchvReward(Base):
    __tablename__ = "achv_rewards"

    tg_id = Column(BigInteger, primary_key=True)
    steps = Column(Integer, primary_key=True)
    reward_type = Column(String, nullable=False)
    reward_value = Column(Integer, nullable=False)
    granted_at = Column(DateTime, default=datetime.utcnow)


class AchvDailyLog(Base):
    __tablename__ = "achv_daily_log"

    tg_id = Column(BigInteger, primary_key=True)
    day = Column(Date, primary_key=True)


class AchvChannelJoin(Base):
    __tablename__ = "achv_channel_join"

    tg_id = Column(BigInteger, primary_key=True)
    joined_at = Column(DateTime, default=datetime.utcnow)


class AchvState(Base):
    __tablename__ = "achv_state"

    tg_id = Column(BigInteger, primary_key=True)
    offset = Column(Integer, default=0)


class AchvNotifyLog(Base):
    __tablename__ = "achv_notify_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tg_id = Column(BigInteger, nullable=False)
    type = Column(String, nullable=False)
    sent_at = Column(DateTime, default=datetime.utcnow)


class AchvProgressAnchor(Base):
    __tablename__ = "achv_progress_anchor"

    tg_id = Column(BigInteger, primary_key=True)
    payments_since = Column(DateTime, default=datetime.utcnow)
