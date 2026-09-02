"""
The three acts the security journal used to miss.

``AuditEvent`` states the rule it is built on: "an act that changes who may
do what leaves a record". Three acts changed exactly that and left none.

* **Registration.** An account came into existence and the journal did not
  say so. Measured before this was written: ``audit.log`` stood at 335
  lines, ``POST /api/v1/auth/register`` answered ``202``, and it stood at
  335 after -- while the same account created at a shell wrote
  ``USER_CREATED``. The sweep that deletes unconfirmed accounts writes
  ``UNVERIFIED_ACCOUNTS_SWEPT``, so the journal could record an account's
  removal without ever having recorded its arrival. That asymmetry is the
  one ``UNVERIFIED_ACCOUNTS_SWEPT`` was itself added to close, on the other
  side.
* **Signing out.** A session ceased, and with it every access token issued
  along its chain. ``grep -ci 'LOGOUT\\|SESSION_REVOKED'`` over all three
  journals answered 0 after a run that revoked eleven sessions.
* **A replayed refresh token.** The single event in this service that means
  a credential of some account is loose. The chain was retired in silence.

Written as one file because they are one property, and because a
"registration is recorded" test that sat beside the registration tests
would be read as being about registration. It is about the journal.

The counts are taken as deltas around each act rather than as absolutes:
the application fixture is shared, so the journal has whatever earlier
tests put in it.
"""

from link_shortener.application.ports.logger.audit import AuditEvent
from tests.integration.conftest import auth_headers, csrf_headers
from tests.integration.web.middleware.test_authentication import (
    _register_and_get_tokens,
)


class TestRegistrationIsOnTheRecord:

    def test_the_count_rises_by_one(self, app, events):
        before = events(AuditEvent.REGISTERED.value)

        with app.test_client() as visitor:
            answered = visitor.post(
                "/api/v1/auth/register",
                json={
                    "email": "journal-registered@example.com",
                    "password": "StrongPass1!",
                },
            )

        assert answered.status_code == 202
        assert events(AuditEvent.REGISTERED.value) == before + 1

    def test_an_address_already_taken_adds_nothing(self, app, events):
        """
        The second attempt creates no account, so it records none.

        Registration answers the same either way on purpose -- the
        response must not say whether an address is taken -- and the
        journal has the opposite obligation only about acts that happened.
        """
        with app.test_client() as visitor:
            visitor.post(
                "/api/v1/auth/register",
                json={
                    "email": "journal-twice@example.com",
                    "password": "StrongPass1!",
                },
            )

        before = events(AuditEvent.REGISTERED.value)

        with app.test_client() as visitor:
            visitor.post(
                "/api/v1/auth/register",
                json={
                    "email": "journal-twice@example.com",
                    "password": "AnotherPass1!",
                },
            )

        assert events(AuditEvent.REGISTERED.value) == before


class TestSigningOutIsOnTheRecord:

    def test_the_count_rises_by_one(self, app, events):
        client = app.test_client()
        access, _ = _register_and_get_tokens(client, "journal-signout@example.com")
        before = events(AuditEvent.SESSION_ENDED.value)

        ended = client.post(
            "/api/v1/auth/logout",
            headers={**auth_headers(access), **csrf_headers(client)},
        )

        assert ended.status_code == 200
        assert events(AuditEvent.SESSION_ENDED.value) == before + 1

    def test_signing_out_twice_records_once(self, app, events):
        """
        The second call ends nothing, and records nothing.

        Made the way a browser makes it -- the cookies were cleared by the
        first, so the second carries no credential at all and is answered
        200: the caller wanted no session and has none. The status is
        therefore not what tells the two apart, and the journal is.
        """
        client = app.test_client()
        access, _ = _register_and_get_tokens(client, "journal-twice-out@example.com")
        client.post(
            "/api/v1/auth/logout",
            headers={**auth_headers(access), **csrf_headers(client)},
        )

        before = events(AuditEvent.SESSION_ENDED.value)
        again = client.post("/api/v1/auth/logout")

        assert again.status_code == 200
        assert events(AuditEvent.SESSION_ENDED.value) == before


class TestAReplayedRefreshTokenIsOnTheRecord:

    def test_the_count_rises_and_the_caller_learns_nothing(self, app, events):
        """
        Both halves at once, because they pull in opposite directions.

        The journal must say a credential is loose; the answer to whoever
        presented it must not, or a thief learns that the token they hold
        was already used and by whom.
        """
        client = app.test_client()
        _register_and_get_tokens(client, "journal-replay@example.com")

        spent = client.get_cookie("refresh_token").value
        rotated = client.post("/api/v1/auth/refresh", headers=csrf_headers(client))
        assert rotated.status_code == 200, rotated.get_data(as_text=True)[:200]

        before = events(AuditEvent.REFRESH_TOKEN_REPLAYED.value)

        # A client of its own, holding no cookie: the route prefers the
        # cookie over the body, so replaying through the same client would
        # spend the *fresh* token the rotation just set and answer 200.
        # Which is how the leaked copy arrives anyway -- somebody else's
        # client, with the token in hand and no session behind it.
        thief = app.test_client()
        replayed = thief.post(
            "/api/v1/auth/refresh", json={"refresh_token": spent}
        )

        assert replayed.status_code == 401
        assert "access_token" not in (replayed.get_json() or {})
        assert events(AuditEvent.REFRESH_TOKEN_REPLAYED.value) == before + 1

    def test_an_ordinary_expired_token_records_nothing(self, app, events):
        """
        Which is what makes the record worth reading.

        A journal that wrote this line for every unusable token would be a
        journal in which "a credential is loose" is the ordinary case.
        """
        before = events(AuditEvent.REFRESH_TOKEN_REPLAYED.value)

        with app.test_client() as caller:
            refused = caller.post(
                "/api/v1/auth/refresh", json={"refresh_token": "not.a.token"}
            )

        assert refused.status_code == 401
        assert events(AuditEvent.REFRESH_TOKEN_REPLAYED.value) == before
