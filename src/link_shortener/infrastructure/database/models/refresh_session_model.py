import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from link_shortener.infrastructure.database.models.base import Base


class RefreshSessionModel(Base):
    """
    ORM model for an issued refresh token.

    One row per token handed out, so that a single session can be retired
    without touching the user's other devices.
    """
    __tablename__ = "refresh_sessions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    token_id: Mapped[str] = mapped_column(
        String(36), unique=True, nullable=False, index=True
    )
    chain_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    replaced_by: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True
    )
