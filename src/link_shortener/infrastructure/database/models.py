import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from link_shortener.infrastructure.database.base import Base


class LinkModel(Base):
    """
    Модель SQLAlchemy для хранения сокращенных ссылок
    """

    __tablename__ = "urls"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    url_hash: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    original_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    short_code: Mapped[str] = mapped_column(
        String(10), unique=True, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, server_default=func.now()
    )
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    last_accessed: Mapped[datetime] = mapped_column(
        DateTime, default=None, nullable=True
    )


# TODO для будущего расширения функционала
# class BlockedURL(Base):
#     """Таблица с заблокированными вредоносными URL"""
#     __tablename__ = 'Blocked_urls'
#     pass
