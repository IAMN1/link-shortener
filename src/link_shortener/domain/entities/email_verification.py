from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid


@dataclass
class EmailVerification:
    """
    One confirmation token issued for an address, tracked so it can be spent.

    Stored rather than signed, and that is the whole reason this entity
    exists. A signed token carries its own validity and cannot be taken
    back: it stays usable until it expires, however many times it is
    presented, whatever happens to the account meanwhile. OWASP asks that a
    token be "Invalidated after they have been used" and "Linked to an
    individual user in the database" -- both are properties of a row, not
    of a signature.

    What is kept is the digest, never the token. A row read out of the
    database is then worth nothing on its own.

    Attributes:
        id: Unique identifier (UUID string).
        user_id: Account whose address this confirms.
        token_hash: SHA-256 digest of the token that was mailed.
        expires_at: When the token stops being accepted.
        created_at: When it was issued.
        used_at: When it was spent, if it was.
    """
    id: str
    user_id: str
    token_hash: str
    expires_at: datetime
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    used_at: Optional[datetime] = None

    @classmethod
    def issue(
        cls,
        user_id: str,
        token_hash: str,
        ttl_hours: int,
        now: Optional[datetime] = None,
    ) -> "EmailVerification":
        """
        Issue a confirmation for an account.

        Args:
            user_id: Account whose address is being confirmed.
            token_hash: Digest of the token that will be mailed.
            ttl_hours: How long the token stays usable.
            now: Issue time; defaults to the current UTC time.

        Returns:
            A new EmailVerification.
        """
        now = now or datetime.now(timezone.utc)
        return cls(
            id=str(uuid.uuid4()),
            user_id=user_id,
            token_hash=token_hash,
            expires_at=now + timedelta(hours=ttl_hours),
            created_at=now,
        )

    def is_usable(self, now: Optional[datetime] = None) -> bool:
        """
        Report whether this confirmation may still be spent.

        Args:
            now: Reference time; defaults to the current UTC time.

        Returns:
            True if it has neither been used nor expired.
        """
        now = now or datetime.now(timezone.utc)
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            # SQLite hands back naive datetimes; treat them as UTC.
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        return self.used_at is None and expires_at > now

    def spend(self, now: Optional[datetime] = None) -> None:
        """
        Mark the confirmation as used, leaving an earlier time alone.

        Args:
            now: Time of use; defaults to the current UTC time.
        """
        if self.used_at is None:
            self.used_at = now or datetime.now(timezone.utc)
