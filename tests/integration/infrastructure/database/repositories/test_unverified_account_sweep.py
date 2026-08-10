"""Unconfirmed accounts must not hold an address forever.

An account that was registered and never confirmed cannot be signed in to,
and blocks anyone from registering that address again -- including the
person who actually owns it. Left alone, that is a way to reserve other
people's addresses in bulk. The sweep is what closes it.
"""

from datetime import datetime, timedelta, timezone

import pytest

from link_shortener.domain import Email, PasswordHash, User


@pytest.fixture()
def uow_factory(app):
    """Unit of Work factory bound to the integration database."""
    with app.app_context():
        yield app.container.get_uow_factory()


def _register(uow_factory, email, verified, age_hours):
    """Store one account of a given age and confirmation state.

    Args:
        uow_factory: Factory for Unit of Work instances.
        email: Address of the account.
        verified: Whether it counts as confirmed.
        age_hours: How long ago it registered.

    Returns:
        The stored User.
    """
    user = User.create(
        email=Email(email),
        password_hash=PasswordHash("$2b$12$" + "x" * 53),
        email_verified=verified,
    )
    user.created_at = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    with uow_factory() as uow:
        uow.users.save(user)
        uow.commit()
    return user


def _cutoff(hours):
    """Registrations older than this are swept."""
    return datetime.now(timezone.utc) - timedelta(hours=hours)


class TestWhatTheSweepTakes:
    """Old and unconfirmed, and nothing else."""

    def test_an_old_unconfirmed_account_is_deleted(self, uow_factory):
        _register(uow_factory, "stale@example.com", verified=False, age_hours=100)

        with uow_factory() as uow:
            deleted = uow.users.delete_unverified_before(_cutoff(72))
            uow.commit()

        assert deleted == 1
        with uow_factory() as uow:
            assert uow.users.find_by_email(Email("stale@example.com")) is None

    def test_a_recent_unconfirmed_account_survives(self, uow_factory):
        """It is still waiting for someone to open their mail."""
        _register(uow_factory, "waiting@example.com", verified=False, age_hours=1)

        with uow_factory() as uow:
            uow.users.delete_unverified_before(_cutoff(72))
            uow.commit()

        with uow_factory() as uow:
            assert uow.users.find_by_email(Email("waiting@example.com")) is not None

    def test_an_old_confirmed_account_survives(self, uow_factory):
        """The one that matters: a sweep that ignored the flag would
        delete every account on the service the first time it ran."""
        _register(uow_factory, "settled@example.com", verified=True, age_hours=10_000)

        with uow_factory() as uow:
            deleted = uow.users.delete_unverified_before(_cutoff(72))
            uow.commit()

        assert deleted == 0
        with uow_factory() as uow:
            assert uow.users.find_by_email(Email("settled@example.com")) is not None

    def test_the_address_becomes_free_again(self, uow_factory):
        """The whole point of the sweep, checked as a registration would
        see it rather than as a row count."""
        _register(uow_factory, "reclaimed@example.com", verified=False, age_hours=100)

        with uow_factory() as uow:
            uow.users.delete_unverified_before(_cutoff(72))
            uow.commit()

        with uow_factory() as uow:
            assert uow.users.find_by_email(Email("reclaimed@example.com")) is None


class TestWhatGoesWithIt:
    """Rows hanging off a swept account must not be left behind."""

    def test_outstanding_confirmations_are_taken_too(self, uow_factory):
        """Otherwise a confirmation link would name an account that no
        longer exists, and the foreign key would refuse the row anyway."""
        from link_shortener.domain.entities.email_verification import (
            EmailVerification,
        )
        from link_shortener.domain.value_objects.verification_token import (
            issue_token,
            token_digest,
        )

        user = _register(
            uow_factory, "orphan@example.com", verified=False, age_hours=100
        )
        token = issue_token()
        with uow_factory() as uow:
            uow.email_verifications.save(
                EmailVerification.issue(
                    user_id=user.id, token_hash=token_digest(token), ttl_hours=24
                )
            )
            uow.commit()

        with uow_factory() as uow:
            uow.users.delete_unverified_before(_cutoff(72))
            uow.commit()

        with uow_factory() as uow:
            assert (
                uow.email_verifications.find_by_token_hash(token_digest(token))
                is None
            )


class TestWhatIsReadBack:
    """The flag has to survive the round trip through the database."""

    def test_confirmation_state_is_stored_and_read(self, uow_factory):
        """A field the ORM writes but never reads back would leave every
        account unconfirmed after a restart, whatever it did before."""
        _register(uow_factory, "roundtrip@example.com", verified=True, age_hours=1)

        with uow_factory() as uow:
            found = uow.users.find_by_email(Email("roundtrip@example.com"))

        assert found.email_verified is True

    def test_an_unconfirmed_account_reads_back_unconfirmed(self, uow_factory):
        _register(uow_factory, "unconfirmed@example.com", verified=False, age_hours=1)

        with uow_factory() as uow:
            found = uow.users.find_by_email(Email("unconfirmed@example.com"))

        assert found.email_verified is False

    def test_confirming_an_account_persists(self, uow_factory):
        user = _register(
            uow_factory, "confirms@example.com", verified=False, age_hours=1
        )

        with uow_factory() as uow:
            stored = uow.users.find_by_id(user.id)
            stored.confirm_email()
            uow.users.save(stored)
            uow.commit()

        with uow_factory() as uow:
            assert uow.users.find_by_id(user.id).email_verified is True
