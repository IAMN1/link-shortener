from datetime import datetime, timezone
from typing import Optional
import uuid
from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from link_shortener.infrastructure.database.models.base import Base


class LinkModel(Base):
    """
    ORM model representing a shortened link.

    Columns:
        id: UUID primary key.
        url_hash: SHA-256 hash of the original URL (unique, indexed).
        original_url: Full original URL.
        short_code: Generated short code (unique, indexed).
        created_at: Creation timestamp (UTC).
        clicks: Number of recorded accesses.
        last_accessed: Timestamp of the most recent access.
        owner_id: Foreign key to the user who created the link (nullable).
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
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now()
    )
    clicks: Mapped[int] = mapped_column(Integer, default=0, index=True)
    last_accessed: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    owner_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
