import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from link_shortener.infrastructure.database.declarative_base import Base


class LinkModel(Base):
    """
    SQLAlchemy model for storing shortened links.

    Attributes:
        id: UUID primary key.
        url_hash: SHA-256 hash of the normalized URL (unique, indexed).
        original_url: The original long URL.
        short_code: Generated short code (unique, indexed).
        created_at: Timestamp of creation.
        clicks: Number of times the link has been accessed.
        last_accessed: Timestamp of the last access (nullable).
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
        DateTime(timezone=True), default=datetime.now(timezone.utc), server_default=func.now()
    )
    clicks: Mapped[int] = mapped_column(Integer, default=0, index=True)
    last_accessed: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=None, nullable=True
    )


# TODO для будущего расширения функционала
# class BlockedURL(Base):
#     """Таблица с заблокированными вредоносными URL"""
#     __tablename__ = 'Blocked_urls'
#     pass
