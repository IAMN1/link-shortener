"""
When a tracked refresh token may still be spent.

``is_usable`` is the whole of the entity's behaviour, and it was reached
only through ``JwtAuthenticationService`` -- where the session is built by
the service itself and every field is whatever that code put there. Two
things went unheld that way: the moment of expiry itself, and the naive
timestamp SQLite hands back, which is the difference between the two
databases this service runs on.
"""

from datetime import datetime, timedelta, timezone

import pytest

from link_shortener.domain.entities.refresh_session import RefreshSession


NOW = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)


def _session(**overrides) -> RefreshSession:
    """A session an hour from expiry, unless the test says otherwise."""
    fields = {
        "id": "session-1",
        "user_id": "user-1",
        "token_id": "jti-1",
        "chain_id": "chain-1",
        "expires_at": NOW + timedelta(hours=1),
    }
    fields.update(overrides)
    return RefreshSession(**fields)


class TestWhatMakesASessionUnusable:

    def test_a_live_session_is_usable(self):
        assert _session().is_usable(now=NOW) is True

    def test_a_revoked_session_is_not(self):
        assert _session(revoked_at=NOW).is_usable(now=NOW) is False

    def test_a_rotated_session_is_not(self):
        assert _session(replaced_by="jti-2").is_usable(now=NOW) is False

    def test_a_session_past_its_expiry_is_not(self):
        session = _session(expires_at=NOW - timedelta(seconds=1))

        assert session.is_usable(now=NOW) is False


class TestTheMomentOfExpiryItself:
    """Expiry is exclusive: at the stroke, the token is already spent.

    The only reference time that tells ``>`` from ``>=`` is the expiry
    itself, and nothing asked for it -- measured, flipping that comparison
    left the whole suite green.
    """

    def test_a_session_at_its_expiry_is_not_usable(self):
        session = _session(expires_at=NOW)

        assert session.is_usable(now=NOW) is False

    def test_one_microsecond_before_it_still_is(self):
        session = _session(expires_at=NOW + timedelta(microseconds=1))

        assert session.is_usable(now=NOW) is True


class TestATimestampWithNoZoneOnIt:
    """
    SQLite returns naive datetimes; PostgreSQL returns aware ones.

    Read as local time, the same row would answer differently on the two
    databases -- and on the same database in two deployments, since the
    offset is the host's. The entity reads a naive stamp as UTC, which is
    what both drivers wrote.
    """

    def test_a_naive_expiry_in_the_future_is_usable(self):
        session = _session(
            expires_at=(NOW + timedelta(hours=1)).replace(tzinfo=None)
        )

        assert session.is_usable(now=NOW) is True

    def test_a_naive_expiry_in_the_past_is_not(self):
        session = _session(
            expires_at=(NOW - timedelta(hours=1)).replace(tzinfo=None)
        )

        assert session.is_usable(now=NOW) is False

    def test_a_naive_expiry_is_not_read_as_local_time(self):
        """Written as a comparison a local reading would get wrong.

        An hour and a half ahead of UTC noon, read in any zone east of
        UTC+2, is already in the past -- so a session this suite calls
        live would be refused on a host in Moscow and accepted in London.
        """
        session = _session(
            expires_at=datetime(2026, 8, 27, 13, 30),
        )

        assert session.is_usable(now=NOW) is True


class TestOpeningASession:

    def test_a_fresh_login_starts_a_chain_named_after_its_own_token(self):
        session = RefreshSession.create(
            user_id="user-1", token_id="jti-1",
            expires_at=NOW + timedelta(days=7),
        )

        assert session.chain_id == "jti-1"

    def test_a_rotation_stays_in_the_chain_it_was_given(self):
        session = RefreshSession.create(
            user_id="user-1", token_id="jti-2",
            expires_at=NOW + timedelta(days=7), chain_id="chain-1",
        )

        assert session.chain_id == "chain-1"

    def test_each_session_gets_its_own_identity(self):
        made = [
            RefreshSession.create(
                user_id="user-1", token_id=f"jti-{index}",
                expires_at=NOW + timedelta(days=7),
            )
            for index in range(2)
        ]

        assert made[0].id != made[1].id

    @pytest.mark.parametrize("field_name", ["revoked_at", "replaced_by"])
    def test_a_new_session_carries_neither_retirement_mark(self, field_name):
        session = RefreshSession.create(
            user_id="user-1", token_id="jti-1",
            expires_at=NOW + timedelta(days=7),
        )

        assert getattr(session, field_name) is None
