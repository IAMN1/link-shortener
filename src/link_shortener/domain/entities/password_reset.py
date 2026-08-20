from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid


@dataclass
class PasswordReset:
    """
    One reset token issued for an account, tracked so it can be spent once.

    A table of its own rather than a column on ``EmailVerification``, and
    the reason is what the two tokens buy. A confirmation proves somebody
    reads a mailbox; a reset replaces the credential and lets the bearer
    into the account. Told apart by a ``purpose`` column, they would be
    told apart by a ``WHERE`` clause in every query that touches them --
    and the one place that clause was forgotten would be a place a
    confirmation link is accepted as a reset link, which is an account
    taken over by following a link its owner asked for. Two tables cannot
    be confused by omission: the query names one of them.

    What is kept is the digest, never the token, for the reason
    ``EmailVerification`` keeps only a digest: a row read out of a backup
    is then worth nothing on its own.

    The lifetime is in minutes rather than hours. That is the other half of
    the difference above -- a link that is a way into the account should
    not sit in a mailbox for a day.

    No ``is_usable`` or ``spend`` here, unlike ``EmailVerification``. The
    rule -- unspent and unexpired -- is decided by the conditional
    ``UPDATE`` inside ``claim``, in one statement, because two requests
    carrying the same link arrive together often enough that a
    check-then-act would let both through. The sibling keeps its pair
    because a fake repository in the tests implements them; a copy here
    that nothing calls would be a second statement of the rule with
    nothing holding it to the first.

    Attributes:
        id: Unique identifier (UUID string).
        user_id: Account whose password this token may replace.
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
        ttl_minutes: int,
        now: Optional[datetime] = None,
    ) -> "PasswordReset":
        """
        Issue a reset token for an account.

        Args:
            user_id: Account whose password it may replace.
            token_hash: Digest of the token that will be mailed.
            ttl_minutes: How long the token stays usable.
            now: Issue time; defaults to the current UTC time.

        Returns:
            A new PasswordReset.
        """
        now = now or datetime.now(timezone.utc)
        return cls(
            id=str(uuid.uuid4()),
            user_id=user_id,
            token_hash=token_hash,
            expires_at=now + timedelta(minutes=ttl_minutes),
            created_at=now,
        )

