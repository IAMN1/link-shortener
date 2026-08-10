"""Every refusal the API makes is answered in the ErrorResponse envelope.

The envelope -- ``error`` as a machine-readable code, ``message`` as the
sentence, ``details`` and a ``timestamp`` -- is what the global error handler
produces and what the OpenAPI document declares. Eleven answers were built by
hand instead: ten carried ``{"error": "<sentence>"}``, so a client reading
``error`` as a code got a sentence from those endpoints and a code from every
other one; the eleventh, the throttle's 429, carried the code but neither
``details`` nor ``timestamp`` -- while the guest-quota 429 beside it, which
goes through the error handler, carried both. One API, two shapes for one
status.

Asserted against the route map rather than against a list, as the
administrative guard beside it is: an endpoint added with an answer built by
hand is a failing test here rather than a discovery in production.
"""

import re

import pytest

from tests.integration.conftest import (
    auth_headers, confirm_email, register_and_login
)


API_PREFIX = "/api/v1"

# Values for parameterised routes. They need not exist: what comes back is
# a refusal either way -- 401 where the guard runs first, 404 where the
# lookup does -- and the envelope is the subject here rather than the status.
PARAMETERS = {
    "user_id": "00000000-0000-0000-0000-000000000000",
    "role_name": "no-such-role",
    "short_code": "nosuch",
}

BODIES = {
    "POST": {"email": "envelope@example.test", "password": "Irrelevant1!"},
    "PUT": {"permissions": []},
    "PATCH": {},
}

# A code, not a sentence: capitals and underscores, and no spaces.
CODE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def api_routes(app):
    """
    Return every ``/api/v1`` route with its parameters filled in.

    Args:
        app: The application whose route map is read.

    Returns:
        List of ``(method, concrete path)`` pairs.

    Raises:
        AssertionError: If a route has a parameter this test cannot fill,
            which would otherwise drop it from the sweep silently.
    """
    found = []
    for rule in app.url_map.iter_rules():
        if not str(rule).startswith(API_PREFIX):
            continue
        path = str(rule)
        for name, value in PARAMETERS.items():
            path = path.replace(f"<{name}>", value)
            path = path.replace(f"<path:{name}>", value)
        if "<" in path:
            raise AssertionError(
                f"route {rule} has a parameter this test does not know how "
                f"to fill; add it to PARAMETERS so the route stays covered"
            )
        for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            found.append((method, path))
    return found


ENVELOPE = {"error", "message", "details", "timestamp"}

# The one field any refusal may carry on top of the envelope. The throttle
# answers it beside the `Retry-After` header, and a client reading the body
# for it exists as surely as one reading the header. Anything else appearing
# here is a second shape for one status, which is what this file is against.
ALLOWED_EXTRAS = {"retry_after"}


def assert_envelope(response, where):
    """
    Assert that a refusal carries the envelope and nothing unexpected.

    Args:
        response: The Flask test-client response to inspect.
        where: Description of the call, for the failure message.
    """
    body = response.get_json()
    assert body is not None, f"{where} answered {response.status_code} with no JSON"
    assert ENVELOPE <= set(body), (
        f"{where} answered {response.status_code} with keys {sorted(body)}, "
        f"missing {sorted(ENVELOPE - set(body))}"
    )
    assert set(body) - ENVELOPE <= ALLOWED_EXTRAS, (
        f"{where} answered {response.status_code} with extra keys "
        f"{sorted(set(body) - ENVELOPE - ALLOWED_EXTRAS)}"
    )
    assert CODE.match(body["error"]), (
        f"{where} answered {response.status_code} with error={body['error']!r}, "
        f"which is a sentence rather than a code"
    )
    assert body["message"], f"{where} answered with an empty message"


class TestEveryRefusalToAnAnonymousCaller:

    def test_the_route_map_has_routes_to_sweep(self, app):
        # A sweep over an empty list passes and proves nothing.
        assert len(api_routes(app)) >= 20

    def test_each_one_refuses_in_the_envelope(self, app, client):
        # Anything the anonymous caller is allowed to do answers 2xx and is
        # not this test's business; everything else has to be an envelope.
        checked = 0
        for method, path in api_routes(app):
            response = client.open(
                path, method=method, json=BODIES.get(method)
            )
            if response.status_code < 400:
                continue
            assert_envelope(response, f"{method} {path}")
            checked += 1

        assert checked >= 15, f"only {checked} refusals were seen"


class TestRefusalsThatNeedAnAccount:

    def test_deleting_a_link_that_is_not_there(self, client):
        token = register_and_login(client, "envelope-owner@example.com")

        response = client.delete(
            "/api/v1/links/nosuch", headers=auth_headers(token)
        )

        assert response.status_code == 404
        assert_envelope(response, "DELETE /api/v1/links/nosuch")
        assert response.get_json()["error"] == "LINK_NOT_FOUND"

    def test_a_route_that_needs_a_login_and_did_not_get_one(self, client):
        response = client.get("/api/v1/links/mine")

        assert response.status_code == 401
        assert_envelope(response, "GET /api/v1/links/mine")
        assert response.get_json()["error"] == "UNAUTHENTICATED"

    @pytest.mark.parametrize("path", [
        "/api/v1/auth/login",
        "/api/v1/auth/register",
    ])
    def test_credentials_that_were_not_sent(self, client, path):
        response = client.post(path, json={})

        assert response.status_code == 400
        assert_envelope(response, f"POST {path}")
        assert response.get_json()["error"] == "VALIDATION_ERROR"

    def test_a_refresh_without_a_token(self, client):
        response = client.post("/api/v1/auth/refresh", json={})

        assert response.status_code == 401
        assert_envelope(response, "POST /api/v1/auth/refresh")
        assert response.get_json()["error"] == "UNAUTHENTICATED"


class TestAdminRefusalsPastTheDoor:
    """The 404s an administrator gets, which no anonymous sweep reaches."""

    @pytest.fixture(autouse=True)
    def setup_admin(self, app, client):
        """Register a user, promote it to admin, and keep its token."""
        with app.app_context():
            from link_shortener.infrastructure.database.seed import (
                seed_base_roles
            )
            db = app.container.get_db_manager()
            with db.session() as session:
                seed_base_roles(session)

        client.post("/api/v1/auth/register", json={
            "email": "envelope-admin@test.com", "password": "AdminPass1!"
        })
        confirm_email(app, "envelope-admin@test.com")

        with app.app_context():
            from sqlalchemy import text
            db = app.container.get_db_manager()
            with db.session() as session:
                user = session.execute(text(
                    "SELECT id FROM users WHERE email='envelope-admin@test.com'"
                )).fetchone()
                admin_role = session.execute(
                    text("SELECT id FROM roles WHERE name='admin'")
                ).fetchone()
                session.execute(text(
                    "INSERT OR IGNORE INTO user_roles (user_id, role_id) "
                    "VALUES (:uid, :rid)"
                ), {"uid": user[0], "rid": admin_role[0]})
                session.commit()

        r = client.post("/api/v1/auth/login", json={
            "email": "envelope-admin@test.com", "password": "AdminPass1!"
        })
        self.token = r.get_json()["access_token"]

    @pytest.mark.parametrize("method, path, status, code", [
        ("GET", f"/api/v1/admin/users/{PARAMETERS['user_id']}", 404,
         "USER_NOT_FOUND"),
        ("DELETE", f"/api/v1/admin/users/{PARAMETERS['user_id']}", 404,
         "USER_NOT_FOUND"),
        ("GET", "/api/v1/admin/roles/no-such-role", 404, "ROLE_NOT_FOUND"),
        # A role that is not there answers 404, like the user endpoint
        # beside it. The two used to disagree: one exception carried both
        # "no such role" and "that one is protected", and the status table
        # maps that code to 400 -- so a name that simply is not there came
        # back as a bad request.
        ("DELETE", "/api/v1/admin/roles/no-such-role", 404, "ROLE_NOT_FOUND"),
    ])
    def test_a_thing_that_is_not_there(self, client, method, path, status, code):
        response = client.open(
            path, method=method, headers=auth_headers(self.token)
        )

        assert response.status_code == status, response.get_json()
        assert_envelope(response, f"{method} {path}")
        assert response.get_json()["error"] == code

    def test_a_protected_role_is_a_bad_request_and_not_a_missing_one(
        self, client
    ):
        """The other half of the split, which nothing covered at all.

        "Not there" and "there, and protected" now answer differently, so
        both have to be pinned -- otherwise collapsing them back into one
        code passes on the strength of the test above.
        """
        response = client.open(
            "/api/v1/admin/roles/admin",
            method="DELETE",
            headers=auth_headers(self.token),
        )

        assert response.status_code == 400, response.get_json()
        assert response.get_json()["error"] == "ROLE_DELETION_FAILED"


class TestTheThrottlesOwnRefusal:
    """The 429 the throttle builds itself, which no sweep above reaches.

    The integration configuration sets ``RATE_LIMIT_AUTH_DISABLED`` and the
    sweep sends one request per route, so the throttle never refuses anything
    in the tests above. It answered ``{error, message, retry_after}`` -- no
    ``details``, no ``timestamp`` -- while the OpenAPI document merges a 429
    declared as ``ErrorResponse`` into thirteen operations, and while the
    guest-quota 429 beside it, raised as a ``DomainError``, carried the full
    envelope. Its own application, because the shared one has the throttle
    turned off for auth and a session-wide counter for everything else.
    """

    @pytest.fixture
    def throttled_app(self):
        """Build an application whose second request is already too many."""
        from link_shortener.web.app_factory import create_app
        from tests.integration.conftest import IntegrationTestConfig

        class OneRequestConfig(IntegrationTestConfig):
            RATE_LIMIT_AUTH_DISABLED = False
            DEFAULT_RATE_LIMIT = 1
            DEFAULT_RATE_LIMIT_PERIOD = 60
            RATE_LIMITS = {}

        application = create_app(config=OneRequestConfig())
        application.config["TESTING"] = True
        with application.app_context():
            db = application.container.get_db_manager()
            db.create_tables()
        return application

    def test_the_throttle_refuses_in_the_envelope(self, throttled_app):
        client = throttled_app.test_client()

        first = client.post("/api/v1/auth/login", json={})
        second = client.post("/api/v1/auth/login", json={})

        assert first.status_code == 400, "the first request was already refused"
        assert second.status_code == 429, second.get_json()
        assert_envelope(second, "POST /api/v1/auth/login (throttled)")
        body = second.get_json()
        assert body["error"] == "RATE_LIMIT_EXCEEDED"
        # The header and the body say the same thing, and both are contract.
        assert body["retry_after"] == 60
        assert second.headers["Retry-After"] == "60"


class TestRefusalsTheAnonymousSweepCannotReach:
    """Two branches the sweep above steps over, and both were unpinned.

    The sweep is anonymous, so a permission check answers it with
    ``UNAUTHENTICATED`` and its ``FORBIDDEN`` branch is never entered; and a
    refresh with no cookie at all takes the first branch, never the one for
    a token that is present and no good. Measured: both could be answered
    with a hand-built ``{"error": "<sentence>"}`` and the whole suite,
    including the live run, stayed green.
    """

    def test_a_permission_that_is_missing_refuses_in_the_envelope(self, client):
        token = register_and_login(client, "envelope-nobody@example.com")

        response = client.get(
            "/api/v1/admin/users", headers=auth_headers(token)
        )

        assert response.status_code == 403
        assert_envelope(response, "GET /api/v1/admin/users (no permission)")
        assert response.get_json()["error"] == "FORBIDDEN"

    def test_a_refresh_token_that_is_no_good_refuses_in_the_envelope(self, client):
        response = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": "not-a-token"}
        )

        assert response.status_code == 401
        assert_envelope(response, "POST /api/v1/auth/refresh (bad token)")
        assert response.get_json()["error"] == "UNAUTHENTICATED"


class TestTheCodeIsPassedThroughAsGiven:
    """``error_response`` must not invent codes out of sentences.

    The sweep's only defence against a sentence in ``error`` is that it
    looks like a code. A helper that tidied its argument into
    ``NOT_AUTHORIZED`` would satisfy the regex with a code that appears in
    no reference and changes whenever the sentence does -- and every check
    in this file would go on passing.
    """

    def test_a_sentence_stays_a_sentence(self, app):
        from link_shortener.web.responses import error_response

        with app.test_request_context():
            response, status = error_response("Not authorized", "why", 403)

        assert response.get_json()["error"] == "Not authorized"
        assert status == 403


class TestTheGuardOnTheServiceStatistics:
    """``/api/v1/stats`` is anonymous only because the guest role says so.

    The decorator is what makes that a setting rather than a fact: take it
    off and the endpoint answers everyone, whatever the role carries, and
    nothing notices -- the route sweep still counts the rule as reached,
    because it measures which rules answered and not which of them asked
    anything first. So the question is put the other way round: with the
    permission taken off the guest role, an anonymous caller has to be
    refused.
    """

    def test_without_the_guest_permission_an_anonymous_caller_is_refused(
        self, app, client
    ):
        from link_shortener.infrastructure.auth import rbac_authorization_service

        before = client.get("/api/v1/stats")
        assert before.status_code == 200, "the endpoint was not open to begin with"

        original = rbac_authorization_service.ANONYMOUS_PERMISSION_CEILING
        rbac_authorization_service.ANONYMOUS_PERMISSION_CEILING = frozenset()
        try:
            response = client.get("/api/v1/stats")
        finally:
            rbac_authorization_service.ANONYMOUS_PERMISSION_CEILING = original

        assert response.status_code == 401, response.get_json()
        assert_envelope(response, "GET /api/v1/stats (guest without the right)")
        assert response.get_json()["error"] == "UNAUTHENTICATED"
