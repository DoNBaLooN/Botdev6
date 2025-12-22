from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime

from database.models import Base


class MaintenanceAttempt(Base):
    __tablename__ = "remnawave_maintenance_attempts"

    tg_id = Column(BigInteger, primary_key=True)
    attempted_at = Column(DateTime, default=datetime.utcnow, nullable=False)
