"""Integration tests for the refresh session repository."""

from datetime import datetime, timedelta, timezone

import pytest

from link_shortener.domain.entities.refresh_session import RefreshSession
from tests.integration.conftest import ensure_user


@pytest.fixture()
def uow_factory(app):
    """Unit of Work factory bound to the integration database."""
    with app.app_context():
        yield app.container.get_uow_factory()


def _open_session(uow_factory, user_id="user-under-test", token_id="tok-1", chain_id=None):
    """
    Store one live session.

    Args:
        uow_factory: Factory for Unit of Work instances.
        user_id: Owner of the session.
        token_id: Token identifier.
        chain_id: Chain to continue; a new one is started when omitted.

    Returns:
        The stored RefreshSession.
    """
    session = RefreshSession.create(
        user_id=user_id,
        token_id=token_id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        chain_id=chain_id,
    )
    with uow_factory() as uow:
        # The account is created first: foreign keys are enforced on SQLite
        # now, as they always were on PostgreSQL, so a session cannot name
        # an account that does not exist.
        ensure_user(uow._session, user_id)
        uow.refresh_sessions.save(session)
        uow.commit()
    return session


class TestClaimForRotation:
    """Spending a session must be exclusive."""

    def test_first_claim_wins_second_loses(self, uow_factory):
        _open_session(uow_factory, token_id="claim-once")

        with uow_factory() as uow:
            first = uow.refresh_sessions.claim_for_rotation("claim-once", "next-a")
            uow.commit()

        with uow_factory() as uow:
            second = uow.refresh_sessions.claim_for_rotation("claim-once", "next-b")
            uow.commit()

        # Two requests reading the same live session both judged it usable
        # before this became a single conditional statement, and each walked
        # away with a successor.
        assert first is True
        assert second is False

    def test_revoked_session_cannot_be_claimed(self, uow_factory):
        _open_session(uow_factory, token_id="claim-revoked")

        with uow_factory() as uow:
            # By its chain, which is what everything here revokes by. A
            # session opened on its own is its own chain.
            uow.refresh_sessions.revoke_chain("claim-revoked")
            uow.commit()

        with uow_factory() as uow:
            claimed = uow.refresh_sessions.claim_for_rotation(
                "claim-revoked", "next"
            )
            uow.commit()

        assert claimed is False

    def test_expired_session_cannot_be_claimed(self, uow_factory):
        expired = RefreshSession.create(
            user_id="user-under-test",
            token_id="claim-expired",
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        with uow_factory() as uow:
            uow.refresh_sessions.save(expired)
            uow.commit()

        with uow_factory() as uow:
            claimed = uow.refresh_sessions.claim_for_rotation(
                "claim-expired", "next"
            )
            uow.commit()

        assert claimed is False

    def test_unknown_session_cannot_be_claimed(self, uow_factory):
        with uow_factory() as uow:
            claimed = uow.refresh_sessions.claim_for_rotation(
                "no-such-token", "next"
            )
            uow.commit()

        assert claimed is False


class TestRevocation:
    """Revocation is scoped, and never silently lost."""

    def test_revoking_twice_counts_only_the_first(self, uow_factory):
        """The count is what the caller reports, so it must not double.

        A password change writes ``sessions_revoked`` into the audit
        journal from this number, and a second pass over an already
        revoked chain would say the account lost its sessions twice.
        """
        _open_session(uow_factory, token_id="revoke-twice")

        with uow_factory() as uow:
            first = uow.refresh_sessions.revoke_chain("revoke-twice")
            uow.commit()
        with uow_factory() as uow:
            second = uow.refresh_sessions.revoke_chain("revoke-twice")
            uow.commit()

        assert first == 1
        assert second == 0

    def test_revoke_chain_spares_other_chains(self, uow_factory):
        _open_session(uow_factory, user_id="chains", token_id="a1")
        _open_session(uow_factory, user_id="chains", token_id="a2", chain_id="a1")
        _open_session(uow_factory, user_id="chains", token_id="b1")

        with uow_factory() as uow:
            revoked = uow.refresh_sessions.revoke_chain("a1")
            uow.commit()

        assert revoked == 2
        with uow_factory() as uow:
            assert uow.refresh_sessions.find_by_token_id("b1").revoked_at is None
            assert uow.refresh_sessions.find_by_token_id("a2").revoked_at is not None

    def test_revoke_all_for_user_takes_every_chain(self, uow_factory):
        _open_session(uow_factory, user_id="blocked", token_id="c1")
        _open_session(uow_factory, user_id="blocked", token_id="c2")

        with uow_factory() as uow:
            revoked = uow.refresh_sessions.revoke_all_for_user("blocked")
            uow.commit()

        assert revoked == 2


class TestCleanup:
    """Expired rows carry no authority and should not accumulate."""

    def test_delete_expired_removes_only_expired(self, uow_factory):
        _open_session(uow_factory, user_id="cleanup", token_id="live-one")
        with uow_factory() as uow:
            uow.refresh_sessions.save(
                RefreshSession.create(
                    user_id="cleanup",
                    token_id="dead-one",
                    expires_at=datetime.now(timezone.utc) - timedelta(days=1),
                )
            )
            uow.commit()

        with uow_factory() as uow:
            uow.refresh_sessions.delete_expired()
            uow.commit()

        with uow_factory() as uow:
            assert uow.refresh_sessions.find_by_token_id("dead-one") is None
            assert uow.refresh_sessions.find_by_token_id("live-one") is not None
