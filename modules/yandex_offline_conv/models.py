from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, String

from database.models import Base


class YandexClientIdMap(Base):
    __tablename__ = "yandex_client_id_map"

    tg_id = Column(BigInteger, primary_key=True)
    cid = Column(String(128), nullable=False)
    counter_tid = Column(String(32))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
