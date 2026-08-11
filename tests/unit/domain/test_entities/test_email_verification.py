"""When a confirmation may be spent, and when it may not.

Includes the state a freshly created account starts in, which belongs
beside these because it is the same rule seen from the other end: a token
is worth something only if the account it confirms was not confirmed
already.

Two of the OWASP requirements for a mailed token are decided entirely
here: that it expires, and that it stops working once used. The third --
that only one caller can spend it -- belongs to the repository, because
only the database can settle a race.
"""

from datetime import datetime, timedelta, timezone

from link_shortener.domain.entities.email_verification import EmailVerification


def issued(ttl_hours=24, now=None):
    """Issue a confirmation for a fixed account.

    Args:
        ttl_hours: Lifetime to issue it with.
        now: Issue time.

    Returns:
        A new EmailVerification.
    """
    return EmailVerification.issue(
        user_id="user-1", token_hash="d" * 64, ttl_hours=ttl_hours, now=now
    )


class TestIssuing:
    """What a freshly issued confirmation looks like."""

    def test_it_expires_after_the_lifetime_it_was_given(self):
        now = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)

        verification = issued(ttl_hours=6, now=now)

        assert verification.expires_at == now + timedelta(hours=6)

    def test_it_starts_unused(self):
        assert issued().used_at is None

    def test_each_one_gets_its_own_identity(self):
        assert issued().id != issued().id

    def test_it_remembers_the_account_it_confirms(self):
        """OWASP: a token has to be linked to an individual user."""
        assert issued().user_id == "user-1"


class TestWhenItCanBeSpent:
    """The two ways a confirmation stops being usable."""

    def test_a_fresh_one_is_usable(self):
        assert issued().is_usable() is True

    def test_an_expired_one_is_not(self):
        long_ago = datetime.now(timezone.utc) - timedelta(days=2)

        assert issued(ttl_hours=1, now=long_ago).is_usable() is False

    def test_it_stops_being_usable_the_moment_it_expires(self):
        """The boundary, checked on both sides: a lifetime that ends at
        exactly ``now`` has ended."""
        now = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
        verification = issued(ttl_hours=1, now=now)

        assert verification.is_usable(now + timedelta(minutes=59)) is True
        assert verification.is_usable(now + timedelta(hours=1)) is False

    def test_a_used_one_is_not(self):
        verification = issued()

        verification.spend()

        assert verification.is_usable() is False

    def test_a_naive_expiry_is_read_as_utc(self):
        """SQLite hands back datetimes with no timezone.

        Compared against an aware ``now``, a naive value raises
        ``TypeError`` rather than answering -- which would turn every
        confirmation on the documented local setup into a 500.
        """
        verification = issued()
        verification.expires_at = datetime.now() + timedelta(hours=1)

        assert verification.is_usable() is True


class TestWhatANewAccountStartsAs:
    """The default that makes every confirmation worth issuing."""

    def test_a_new_account_is_unconfirmed(self):
        """Flip this and self-registration hands out confirmed accounts to
        anyone naming any address -- the confirmation still gets mailed,
        still works, and no longer decides anything."""
        from link_shortener.domain import Email, PasswordHash, User

        user = User.create(
            email=Email("someone@example.com"),
            password_hash=PasswordHash("$2b$12$" + "x" * 53),
        )

        assert user.email_verified is False

    def test_an_account_can_be_created_already_confirmed(self):
        """What an administrator creating an account gets: nobody is going
        to mail that person a link."""
        from link_shortener.domain import Email, PasswordHash, User

        user = User.create(
            email=Email("someone@example.com"),
            password_hash=PasswordHash("$2b$12$" + "x" * 53),
            email_verified=True,
        )

        assert user.email_verified is True

    def test_confirming_sets_the_flag(self):
        from link_shortener.domain import Email, PasswordHash, User

        user = User.create(
            email=Email("someone@example.com"),
            password_hash=PasswordHash("$2b$12$" + "x" * 53),
        )

        user.confirm_email()

        assert user.email_verified is True


class TestSpending:
    """Used once means used once."""

    def test_spending_records_the_time(self):
        now = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
        verification = issued()

        verification.spend(now)

        assert verification.used_at == now

    def test_spending_twice_keeps_the_first_time(self):
        """The second call is the suspicious one -- a replayed link -- and
        it must not rewrite the record of when the first arrived."""
        first = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
        verification = issued()

        verification.spend(first)
        verification.spend(first + timedelta(hours=1))

        assert verification.used_at == first
