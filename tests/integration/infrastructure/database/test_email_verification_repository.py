"""Integration tests for the email confirmation repository.

The rules OWASP states for a mailed token -- single use, expiring, linked
to one account, stored as something other than itself -- are only really
rules once the database enforces them. This is where that is checked.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, text

from link_shortener.domain.entities.email_verification import EmailVerification
from link_shortener.domain.value_objects.verification_token import (
    issue_token,
    token_digest,
)
from tests.integration.conftest import ensure_user


@pytest.fixture()
def uow_factory(app):
    """Unit of Work factory bound to the integration database."""
    with app.app_context():
        yield app.container.get_uow_factory()


def _issue(uow_factory, user_id="user-under-test", token=None, ttl_hours=24, now=None):
    """Store one confirmation and return the token that opens it.

    Args:
        uow_factory: Factory for Unit of Work instances.
        user_id: Account being confirmed.
        token: Token to use; a fresh one is minted when omitted.
        ttl_hours: Lifetime of the confirmation.
        now: Issue time.

    Returns:
        Tuple of (token, stored EmailVerification).
    """
    token = token or issue_token()
    verification = EmailVerification.issue(
        user_id=user_id,
        token_hash=token_digest(token),
        ttl_hours=ttl_hours,
        now=now,
    )
    with uow_factory() as uow:
        ensure_user(uow._session, user_id)
        uow.email_verifications.save(verification)
        uow.commit()
    return token, verification


class TestClaiming:
    """Spending a confirmation must be exclusive and final."""

    def test_a_live_token_names_its_account(self, uow_factory):
        token, _ = _issue(uow_factory, user_id="claimant")

        with uow_factory() as uow:
            owner = uow.email_verifications.claim(token_digest(token))
            uow.commit()

        assert owner == "claimant"

    def test_the_second_claim_gets_nothing(self, uow_factory):
        """A link opened twice -- a prefetching mail client, a double
        click -- must confirm once and refuse the rest."""
        token, _ = _issue(uow_factory)

        with uow_factory() as uow:
            first = uow.email_verifications.claim(token_digest(token))
            uow.commit()
        with uow_factory() as uow:
            second = uow.email_verifications.claim(token_digest(token))
            uow.commit()

        assert first is not None
        assert second is None

    def test_an_expired_token_is_refused(self, uow_factory):
        long_ago = datetime.now(timezone.utc) - timedelta(days=3)
        token, _ = _issue(uow_factory, ttl_hours=1, now=long_ago)

        with uow_factory() as uow:
            owner = uow.email_verifications.claim(token_digest(token))
            uow.commit()

        assert owner is None

    def test_an_unknown_token_is_refused(self, uow_factory):
        with uow_factory() as uow:
            owner = uow.email_verifications.claim(token_digest("never-issued"))
            uow.commit()

        assert owner is None

    def test_claiming_records_when_it_was_spent(self, uow_factory):
        token, _ = _issue(uow_factory)

        with uow_factory() as uow:
            uow.email_verifications.claim(token_digest(token))
            uow.commit()

        with uow_factory() as uow:
            stored = uow.email_verifications.find_by_token_hash(token_digest(token))

        assert stored.used_at is not None

    def test_the_database_is_what_decides(self, uow_factory):
        """The spend must be a conditional UPDATE, not a read then a write.

        Asserted on the SQL because nothing else can see the difference:
        a version that reads the row, checks it in Python and then writes
        by primary key passes every other test in this file -- claims are
        made one after another here -- and loses the race in production,
        where two requests carrying the same link both read a usable row
        and both write.
        """
        token, _ = _issue(uow_factory)
        statements = []

        with uow_factory() as uow:
            engine = uow._session.get_bind()

            @event.listens_for(engine, "before_cursor_execute")
            def record(conn, cursor, statement, *rest):
                statements.append(" ".join(statement.split()))

            try:
                uow.email_verifications.claim(token_digest(token))
                uow.commit()
            finally:
                event.remove(engine, "before_cursor_execute", record)

        updates = [s for s in statements if s.upper().startswith("UPDATE")]
        assert len(updates) == 1, statements
        assert "used_at IS NULL" in updates[0], updates[0]
        assert "expires_at >" in updates[0], updates[0]

    def test_an_expired_token_is_not_marked_used(self, uow_factory):
        """The refusal must come from the filter, not from spending it.

        A statement that stamped ``used_at`` first and judged afterwards
        would answer the same way here and leave the wrong record behind.
        """
        long_ago = datetime.now(timezone.utc) - timedelta(days=3)
        token, _ = _issue(uow_factory, ttl_hours=1, now=long_ago)

        with uow_factory() as uow:
            uow.email_verifications.claim(token_digest(token))
            uow.commit()

        with uow_factory() as uow:
            stored = uow.email_verifications.find_by_token_hash(token_digest(token))

        assert stored.used_at is None


class TestWhatIsStored:
    """The row must not be usable as the link it stands for."""

    def test_the_token_itself_is_never_written(self, uow_factory):
        token, _ = _issue(uow_factory, user_id="secret-keeper")

        with uow_factory() as uow:
            rows = list(
                uow._session.execute(text("SELECT * FROM email_verifications"))
            )

        assert token not in str(rows), "the mailed token reached the table"

    def test_the_stored_digest_is_what_lookup_uses(self, uow_factory):
        token, verification = _issue(uow_factory)

        with uow_factory() as uow:
            found = uow.email_verifications.find_by_token_hash(token_digest(token))

        assert found.id == verification.id
        assert found.token_hash == token_digest(token)


class TestInvalidating:
    """Issuing a new confirmation retires the ones already out."""

    def test_older_confirmations_stop_working(self, uow_factory):
        old_token, _ = _issue(uow_factory, user_id="re-sender")

        with uow_factory() as uow:
            uow.email_verifications.invalidate_for_user("re-sender")
            uow.commit()

        with uow_factory() as uow:
            owner = uow.email_verifications.claim(token_digest(old_token))
            uow.commit()

        assert owner is None

    def test_it_reports_how_many_it_retired(self, uow_factory):
        _issue(uow_factory, user_id="counted")
        _issue(uow_factory, user_id="counted")

        with uow_factory() as uow:
            retired = uow.email_verifications.invalidate_for_user("counted")
            uow.commit()

        assert retired == 2

    def test_another_account_is_left_alone(self, uow_factory):
        mine, _ = _issue(uow_factory, user_id="mine")
        _issue(uow_factory, user_id="theirs")

        with uow_factory() as uow:
            uow.email_verifications.invalidate_for_user("theirs")
            uow.commit()

        with uow_factory() as uow:
            owner = uow.email_verifications.claim(token_digest(mine))
            uow.commit()

        assert owner == "mine"


class TestSweeping:
    """Dead rows go; live ones stay."""

    def test_expired_confirmations_are_deleted(self, uow_factory):
        long_ago = datetime.now(timezone.utc) - timedelta(days=3)
        token, _ = _issue(uow_factory, ttl_hours=1, now=long_ago)

        with uow_factory() as uow:
            uow.email_verifications.delete_expired()
            uow.commit()

        with uow_factory() as uow:
            assert (
                uow.email_verifications.find_by_token_hash(token_digest(token))
                is None
            )

    def test_spent_confirmations_are_deleted_too(self, uow_factory):
        """A used row is as dead as an expired one and would otherwise sit
        there for as long as the account exists."""
        token, _ = _issue(uow_factory)

        with uow_factory() as uow:
            uow.email_verifications.claim(token_digest(token))
            uow.commit()
        with uow_factory() as uow:
            uow.email_verifications.delete_expired()
            uow.commit()

        with uow_factory() as uow:
            assert (
                uow.email_verifications.find_by_token_hash(token_digest(token))
                is None
            )

    def test_a_live_confirmation_survives(self, uow_factory):
        token, _ = _issue(uow_factory)

        with uow_factory() as uow:
            uow.email_verifications.delete_expired()
            uow.commit()

        with uow_factory() as uow:
            owner = uow.email_verifications.claim(token_digest(token))
            uow.commit()

        assert owner is not None


class TestTheAccountItHangsOff:
    """Confirmations do not outlive the account they confirm."""

    def test_deleting_the_account_takes_its_confirmations(self, uow_factory):
        """``ON DELETE CASCADE``, which SQLite only honours because the
        manager sets the pragma on every connection."""
        token, _ = _issue(uow_factory, user_id="doomed")

        with uow_factory() as uow:
            uow.users.delete("doomed")
            uow.commit()

        with uow_factory() as uow:
            assert (
                uow.email_verifications.find_by_token_hash(token_digest(token))
                is None
            )
