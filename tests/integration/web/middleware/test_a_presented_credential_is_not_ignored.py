"""
A credential the caller presented is answered, not quietly stepped over.

``AuthenticationMiddleware`` used to leave the request anonymous whenever a
token failed any of its checks. On a route that needs an account that shows
up as ``401`` and reads correctly. On a route an anonymous caller may also
use it does not: measured on a live stack, a deactivated account's token
answered ``401`` on ``/api/v1/links/mine`` and ``/api/v1/stats/mine`` and
**201** on ``POST /api/v1/shorten``, where the link was made as a guest --
``owner_id: null``, a guest lifetime, and out of the caller's own listing.
The caller was told their link was made; it was made as somebody else.

That is the shape ``web/schemas/strict.py`` refuses for a body -- "the
service accepts a field, answers 201, and does nothing with it, which is
the one answer a caller cannot tell from success" -- and a credential is a
worse thing to accept and ignore than a field.

The line drawn is the source of the token, and the two halves are both
tested here.

* An ``Authorization: Bearer`` header is a caller deliberately presenting a
  credential. RFC 6750 asks for ``invalid_token`` rather than silence, and
  the service now refuses.
* The ``access_token`` cookie is what a browser goes on sending after a
  session ends. Refusing that would answer ``401`` to a visitor opening a
  public page, so it still falls back to anonymous -- and the second class
  below is what keeps that from being "fixed" by mistake.
"""

import itertools

import pytest

from tests.integration.conftest import auth_headers, csrf_headers
from tests.integration.web.middleware.test_authentication import (
    _deactivate_user,
    _register_and_get_tokens,
)


ANONYMOUS_FRIENDLY = "/api/v1/shorten"
"""A route an anonymous caller may use, which is where silence hid."""

_addresses = itertools.count()


def a_guest_client(app, address: str):
    """
    A client the service counts as a guest of its own.

    The allowance is per address, so tests that make guest links from the
    shared client spend an allowance later tests are counting on: the
    deduplication tests two files away began failing in a full run and
    passing alone, which is the shape that says a fixture leaked.
    """
    client = app.test_client()
    client.environ_base["REMOTE_ADDR"] = address
    return client


def an_address(prefix: str) -> str:
    """
    An address no earlier test in this file has switched off.

    The application fixture is built once for the session, so an address
    reused across tests is the same account -- and these tests deactivate
    the accounts they make, which left the next registration a no-op and
    its sign-in a 401 during setup.
    """
    return f"{prefix}-{next(_addresses)}@example.com"


@pytest.fixture
def revoked(app, db):
    """A real token whose account has since been switched off."""
    email = an_address("presented-revoked")
    client = app.test_client()
    access, refresh = _register_and_get_tokens(client, email)
    _deactivate_user(db, email)
    return {"access_token": access, "refresh_token": refresh}


class TestARejectedBearerTokenIsRefused:

    def test_on_a_route_that_needs_an_account(self, app, revoked):
        """Unchanged, and here so the pair below is a comparison."""
        with app.test_client() as caller:
            r = caller.get(
                "/api/v1/links/mine", headers=auth_headers(revoked["access_token"])
            )

        assert r.status_code == 401

    def test_on_a_route_an_anonymous_caller_may_also_use(self, app, revoked):
        """The one that answered 201."""
        with a_guest_client(app, "192.0.2.181") as caller:
            r = caller.post(
                ANONYMOUS_FRIENDLY,
                json={"url": "https://example.com/revoked-presented"},
                headers=auth_headers(revoked["access_token"]),
            )

        assert r.status_code == 401
        assert r.get_json()["error"] == "UNAUTHENTICATED"

    def test_and_nothing_was_created_under_it(self, app, revoked):
        """
        The half a status code does not cover.

        A refusal that still wrote the row would leave the caller's link in
        somebody else's hands and the caller told it failed.
        """
        url = "https://example.com/revoked-created-nothing"
        with a_guest_client(app, "192.0.2.182") as caller:
            caller.post(
                ANONYMOUS_FRIENDLY,
                json={"url": url},
                headers=auth_headers(revoked["access_token"]),
            )

        with a_guest_client(app, "192.0.2.183") as anyone:
            made = anyone.post(ANONYMOUS_FRIENDLY, json={"url": url})
        # Nobody had made it, so this is a creation rather than the
        # deduplicated answer an existing row would have produced.
        assert made.status_code == 201
        assert made.get_json()["is_new"] is True

    @pytest.mark.parametrize("presented", [
        "Bearer not.a.token.at.all",
        "Bearer eyJhbGciOiJIUzI1NiJ9.e30.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    ])
    def test_a_token_that_was_never_valid(self, app, presented):
        with a_guest_client(app, "192.0.2.184") as caller:
            r = caller.post(
                ANONYMOUS_FRIENDLY,
                json={"url": "https://example.com/garbage-bearer"},
                headers={"Authorization": presented},
            )

        assert r.status_code == 401

    def test_a_refresh_token_offered_as_an_access_token(self, app):
        """
        The wrong kind of credential is still a credential.

        It used to be ignored, which meant a client that had muddled the
        two got ``201`` and no hint that its access token was never used.
        """
        client = app.test_client()
        _, refresh = _register_and_get_tokens(client, an_address("presented-refresh"))

        with a_guest_client(app, "192.0.2.185") as caller:
            r = caller.post(
                ANONYMOUS_FRIENDLY,
                json={"url": "https://example.com/refresh-as-access"},
                headers=auth_headers(refresh),
            )

        assert r.status_code == 401


class TestAStaleCookieStillFallsBackToAnonymous:
    """
    The half that must not be "fixed".

    Every browser goes on sending ``access_token`` after the session behind
    it ends. Refusing that would answer ``401`` to somebody opening the
    landing page, which is a public page.
    """

    @pytest.fixture
    def stale_cookie(self, app, db):
        email = an_address("presented-stale")
        client = a_guest_client(app, "192.0.2.186")
        _register_and_get_tokens(client, email)
        _deactivate_user(db, email)
        return client

    def test_a_public_page_still_opens(self, stale_cookie):
        assert stale_cookie.get("/").status_code == 200

    def test_an_anonymous_write_still_goes_through(self, stale_cookie):
        r = stale_cookie.post(
            ANONYMOUS_FRIENDLY,
            json={"url": "https://example.com/stale-cookie-write"},
            headers=csrf_headers(stale_cookie),
        )

        assert r.status_code == 201
        assert r.get_json()["owner_id"] is None

    def test_health_still_answers(self, stale_cookie):
        assert stale_cookie.get("/health").status_code in (200, 503)


class TestTheWayOutOfAnExpiredTokenStaysOpen:
    """
    Three endpoints do not run on this header, and two are the way out.

    Refusing a presented credential is right where the credential is what
    the endpoint runs on. ``/auth/refresh`` and ``/auth/logout`` identify
    the caller by the refresh token in the cookie and read this header
    never -- they exist **for** the client whose access token has expired,
    which is precisely the client the refusal turned away.

    Measured before the exception existed, on a live session holding a
    valid refresh cookie, the correct CSRF header, and its own access token
    with ``exp`` in the past::

        POST /auth/refresh   no header           -> 200, tokens issued
        POST /auth/refresh   + the expired one   -> 401 UNAUTHENTICATED
        POST /auth/logout    + the expired one   -> 401 UNAUTHENTICATED

    and both answered ``200`` on the tree before the refusal landed. A
    client that puts its ``Authorization`` on every request -- the ordinary
    way to write one -- could then neither refresh nor sign out, and had
    nothing left but to clear its own storage by hand.

    ``/health`` is here for a different reason of the same kind: it is the
    observation route, exempt from the rate limiter already, and a monitor
    walking the service with one client and a token that has since expired
    was told ``401`` by the endpoint whose whole job is to say whether the
    service is well.
    """

    @pytest.fixture
    def signed_in(self, app):
        """A live session, and an access token of its own that has expired."""
        import datetime

        from link_shortener.domain.value_objects.email import Email

        email = an_address("expired-header")
        client = a_guest_client(app, "192.0.2.201")
        access, _ = _register_and_get_tokens(client, email)

        with app.app_context():
            auth = app.container.get_authentication_service()
            claims = auth.validate_token(access, expected_type="access")
            with app.container.get_uow_factory()(read_only=True) as uow:
                user = uow.users.find_by_email(Email(email))
            expired = auth._create_token(
                user,
                datetime.timedelta(seconds=-30),
                "access",
                session_id=claims["sid"],
            )
        return client, expired

    def test_refreshing_works_while_holding_the_expired_token(self, signed_in):
        """The case the exception exists for."""
        client, expired = signed_in

        answered = client.post(
            "/api/v1/auth/refresh",
            headers=csrf_headers(client, {"Authorization": f"Bearer {expired}"}),
        )

        assert answered.status_code == 200, answered.get_data(as_text=True)[:200]
        assert "access_token" in answered.get_json()

    def test_signing_out_works_while_holding_it(self, signed_in):
        client, expired = signed_in

        answered = client.post(
            "/api/v1/auth/logout",
            headers=csrf_headers(client, {"Authorization": f"Bearer {expired}"}),
        )

        assert answered.status_code == 200, answered.get_data(as_text=True)[:200]

    def test_health_answers_a_caller_holding_one(self, app, signed_in):
        """
        The observation route says how the service is, not who is asking.

        A monitor that walks the service with one client is the ordinary
        way to run one, and the token it started with expires.
        """
        client, expired = signed_in

        answered = client.get(
            "/health", headers={"Authorization": f"Bearer {expired}"}
        )

        assert answered.status_code in (200, 503)
        assert "components" in answered.get_json()

    @pytest.mark.parametrize("path, body", [
        ("/api/v1/auth/register", {"email": "way-in-1@example.com",
                                   "password": "StrongPass1!"}),
        ("/api/v1/auth/forgot-password", {"email": "way-in-1@example.com"}),
        ("/api/v1/auth/resend-verification", {"email": "way-in-1@example.com"}),
    ])
    def test_no_way_in_is_closed_by_a_token(self, app, signed_in, path, body):
        """
        Every route under `auth` is a way in, and none runs on this header.

        The first version of this exemption named three endpoints --
        refresh, logout, health -- and left the rest shut. Measured with a
        stale header on routes that had never seen it: register, the reset
        request and the resend all answered 401 instead of 202, and signing
        in with the right password answered 401 instead of issuing a pair.
        A client that puts Authorization on every request had no way back
        at all.
        """
        _, expired = signed_in
        caller = a_guest_client(app, "192.0.2.202")

        answered = caller.post(
            path, json=body,
            headers=csrf_headers(
                caller, {"Authorization": f"Bearer {expired}"}
            ),
        )

        assert answered.status_code != 401, answered.get_data(as_text=True)[:200]

    def test_signing_in_works_while_holding_one(self, app, signed_in):
        """The case that matters most: the way back to a working token."""
        email = an_address("way-back")
        opener = a_guest_client(app, "192.0.2.203")
        _register_and_get_tokens(opener, email)
        _, expired = signed_in

        caller = app.test_client()
        answered = caller.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "StrongPass1!"},
            headers={"Authorization": f"Bearer {expired}"},
        )

        assert answered.status_code == 200, answered.get_data(as_text=True)[:200]
        assert "access_token" in answered.get_json()

    def test_every_other_route_still_refuses_it(self, app, signed_in):
        """
        The half that keeps the exception narrow.

        Without this, "the way out stays open" could be satisfied by
        dropping the refusal altogether.
        """
        client, expired = signed_in

        answered = client.post(
            ANONYMOUS_FRIENDLY,
            json={"url": "https://example.com/expired-elsewhere"},
            headers=csrf_headers(client, {"Authorization": f"Bearer {expired}"}),
        )

        assert answered.status_code == 401
        assert answered.get_json()["error"] == "UNAUTHENTICATED"
