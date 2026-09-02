from datetime import datetime, timezone
from typing import Optional
import uuid
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from link_shortener.infrastructure.database.models.base import Base


class LinkModel(Base):
    """
    ORM model representing a shortened link.

    Maps to the ``urls`` table and holds all persistent fields of a link,
    including audit metadata, click counts, and optional expiration.

    Attributes:
        id: UUID primary key, auto-generated if not provided.
        url_hash: SHA-256 hash of the original URL, indexed together with the
            owner for deduplication. Deliberately not unique: deduplication
            is per owner and skips expired links, so the same hash may
            legitimately appear more than once -- the index in
            ``migrations/versions/0001_initial_schema.py`` is not unique,
            deliberately.
        original_url: Full original URL, up to 2048 characters.
        short_code: Generated short code (6-10 chars), unique and indexed.
        created_at: Timestamp when the link was created (UTC).
        clicks: Number of recorded accesses (default 0).
        last_accessed: Timestamp of the most recent access (nullable).
        owner_id: Foreign key to the ``users`` table; ``NULL`` for guest links,
            ``CASCADE`` on user deletion -- a link does not outlive the
            account that made it. The deletion is carried out by
            ``DeleteUserUseCase`` so that the caches are cleared with it;
            this is the backstop for a deletion done outside the
            application.
        expires_at: Optional expiration timestamp; ``NULL`` means never expires.
        guest_identifier: Optional identifier for guest-created links
            (e.g. IP address), stored for rate limiting purposes.
    """
    __tablename__ = "urls"

    __table_args__ = (
        # One index per shape the deduplication lookup is asked in: by
        # owning account, or by the identifier a guest's links are grouped
        # under.
        Index("ix_urls_url_hash_owner_id", "url_hash", "owner_id"),
        Index(
            "ix_urls_url_hash_guest_identifier", "url_hash", "guest_identifier"
        ),
        # The guest quota, read before every guest creation: equality on the
        # identifier, a range on the timestamp -- the one order a B-tree can
        # use both of.
        Index(
            "ix_urls_guest_identifier_created_at",
            "guest_identifier", "created_at",
        ),
        # The expiry sweep. Without it both of these were sequential scans
        # growing with the table rather than with the answer.
        Index("ix_urls_expires_at", "expires_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    url_hash: Mapped[str] = mapped_column(
        String(64), nullable=False
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
        String(36),
        ForeignKey("users.id", ondelete="CASCADE", name="fk_urls_owner_id_users"),
        nullable=True,
        index=True,
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    guest_identifier: Mapped[Optional[str]] = mapped_column(
        String(45), nullable=True
    )
