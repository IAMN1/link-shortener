import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from link_shortener.domain.value_objects.verification_token import DIGEST_LENGTH
from link_shortener.infrastructure.database.models.base import Base


class EmailVerificationModel(Base):
    """
    ORM model for one issued address confirmation.

    One row per token handed out, so that a token can be spent exactly once
    and the older ones an account may still have outstanding can be retired
    without touching anything else.
    """
    __tablename__ = "email_verifications"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(
        String(DIGEST_LENGTH), unique=True, nullable=False, index=True
    )
    """The digest of the mailed token, never the token.

    Width comes from the rule that produces it rather than a literal
    repeated here: a column narrower than the digest stores a prefix, and a
    prefix never matches on lookup. Unique because two accounts sharing a
    digest would mean two accounts sharing a token.
    """

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
