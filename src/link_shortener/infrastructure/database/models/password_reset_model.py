import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from link_shortener.domain.value_objects.verification_token import DIGEST_LENGTH
from link_shortener.infrastructure.database.models.base import Base


class PasswordResetModel(Base):
    """
    ORM model for one issued password reset token.

    A table of its own beside ``email_verifications`` rather than a row in
    it under another ``purpose``. The two carry the same columns and mean
    different things: this one is a way into the account, and a query that
    forgot to filter by purpose would accept one for the other. See
    ``PasswordReset`` for the full reasoning.
    """
    __tablename__ = "password_resets"

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

    Width from the rule that produces it, as in ``email_verifications``: a
    column narrower than the digest stores a prefix, and a prefix never
    matches on lookup. Unique because two accounts sharing a digest would
    be two accounts one link opens.
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
