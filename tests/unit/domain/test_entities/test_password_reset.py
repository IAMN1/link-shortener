"""What a freshly issued reset token looks like.

Shorter than the file beside it, and deliberately so: this entity has no
``is_usable`` and no ``spend``. Whether a token may still be spent is
settled by the conditional ``UPDATE`` in the repository, in one statement,
because two requests carrying the same link arrive together often enough
that a check-then-act would let both through -- and for this token letting
both through means two password changes from one link.

What is left here is the arithmetic nothing else states: the lifetime is
in minutes, not hours, and a copy of that rule written in the wrong unit
is a link that lives sixty times too long.
"""

from datetime import datetime, timedelta, timezone

from link_shortener.domain.entities.password_reset import PasswordReset


def issued(ttl_minutes=60, now=None):
    """Issue a reset token for a fixed account.

    Args:
        ttl_minutes: Lifetime to issue it with.
        now: Issue time.

    Returns:
        A new PasswordReset.
    """
    return PasswordReset.issue(
        user_id="user-1", token_hash="d" * 64, ttl_minutes=ttl_minutes, now=now
    )


class TestIssuing:
    """What a freshly issued token looks like."""

    def test_it_expires_after_the_lifetime_it_was_given(self):
        now = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)

        reset = issued(ttl_minutes=30, now=now)

        assert reset.expires_at == now + timedelta(minutes=30)

    def test_the_lifetime_is_read_as_minutes(self):
        """The unit, asserted rather than assumed.

        ``EmailVerification.issue`` takes hours and this one takes
        minutes, and the two signatures differ by one word. Read as hours,
        the default lifetime would be sixty times what the message
        promises and what the decision record states.
        """
        now = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)

        reset = issued(ttl_minutes=60, now=now)

        assert reset.expires_at == now + timedelta(hours=1)

    def test_it_starts_unused(self):
        assert issued().used_at is None

    def test_each_one_gets_its_own_identity(self):
        assert issued().id != issued().id

    def test_it_remembers_the_account_it_opens(self):
        """OWASP: a token has to be linked to an individual user."""
        assert issued().user_id == "user-1"

    def test_it_keeps_the_digest_it_was_given(self):
        # The digest, never the token: a row read out of a backup is then
        # worth nothing on its own.
        assert issued().token_hash == "d" * 64
