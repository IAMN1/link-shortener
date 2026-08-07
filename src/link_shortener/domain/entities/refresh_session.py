from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
import uuid


@dataclass
class RefreshSession:
    """
    One issued refresh token, tracked so that it can be revoked.

    A refresh token is a bearer credential that outlives the access token by
    days, so the service has to be able to retire a specific one: on logout,
    when it is rotated, or when a token that was already spent shows up again
    -- the signature that it was copied.

    Attributes:
        id: Unique identifier (UUID string).
        user_id: Owner of the session.
        token_id: The ``jti`` claim carried by the refresh token itself.
        chain_id: Identifies the succession of tokens this one descends
            from -- one login, however many times its token was rotated.
            Retiring a compromised token takes down its chain and leaves the
            user's other devices alone.
        expires_at: When the underlying token stops being valid.
        created_at: When the session was opened.
        revoked_at: When it was retired, if it was.
        replaced_by: ``token_id`` of the session that superseded this one
            during rotation.
    """
    id: str
    user_id: str
    token_id: str
    chain_id: str
    expires_at: datetime
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    revoked_at: Optional[datetime] = None
    replaced_by: Optional[str] = None

    @classmethod
    def create(
        cls,
        user_id: str,
        token_id: str,
        expires_at: datetime,
        chain_id: Optional[str] = None,
    ) -> "RefreshSession":
        """
        Open a session for a freshly issued refresh token.

        Args:
            user_id: Owner of the session.
            token_id: The ``jti`` embedded in the token.
            expires_at: Expiry of the token.
            chain_id: Chain this session continues; omitted for a fresh
                login, which starts a chain named after its own token.

        Returns:
            A new RefreshSession.
        """
        return cls(
            id=str(uuid.uuid4()),
            user_id=user_id,
            token_id=token_id,
            chain_id=chain_id or token_id,
            expires_at=expires_at,
        )

    def is_usable(self, now: Optional[datetime] = None) -> bool:
        """
        Report whether the token behind this session may still be spent.

        Args:
            now: Reference time; defaults to the current UTC time.

        Returns:
            True if the session is neither revoked, nor already rotated,
            nor expired.
        """
        now = now or datetime.now(timezone.utc)
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            # SQLite hands back naive datetimes; treat them as UTC.
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        return (
            self.revoked_at is None
            and self.replaced_by is None
            and expires_at > now
        )

    def revoke(self, now: Optional[datetime] = None) -> None:
        """
        Retire the session, leaving an already-set revocation time alone.

        Args:
            now: Revocation time; defaults to the current UTC time.
        """
        if self.revoked_at is None:
            self.revoked_at = now or datetime.now(timezone.utc)
