from datetime import datetime, timezone
from typing import Optional
import uuid
from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from link_shortener.infrastructure.database.models.base import Base


class LinkModel(Base):
    """
    ORM model representing a shortened link.

    Maps to the ``urls`` table and holds all persistent fields of a link,
    including audit metadata, click counts, and optional expiration.

    Attributes:
        id: UUID primary key, auto-generated if not provided.
        url_hash: SHA-256 hash of the original URL; unique and indexed for
            deduplication.
        original_url: Full original URL, up to 2048 characters.
        short_code: Generated short code (6-10 chars), unique and indexed.
        created_at: Timestamp when the link was created (UTC).
        clicks: Number of recorded accesses (default 0).
        last_accessed: Timestamp of the most recent access (nullable).
        owner_id: Foreign key to the ``users`` table; ``NULL`` for guest links,
            ``SET NULL`` on user deletion.
        expires_at: Optional expiration timestamp; ``NULL`` means never expires.
        guest_identifier: Optional identifier for guest-created links
            (e.g. IP address), stored for rate limiting purposes.
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
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    guest_identifier: Mapped[Optional[str]] = mapped_column(
        String(45), nullable=True
    )
