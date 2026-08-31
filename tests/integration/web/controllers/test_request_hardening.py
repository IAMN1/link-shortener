"""
Tests that a malformed request is refused rather than survived.

Three ways an anonymous caller can reach a 500 in the two creation
endpoints, none of them needing an account:

- a body that is valid JSON but not an object. The schemas are handed the
  body as keyword arguments, and ``**`` on a list or a string raises
  ``TypeError`` before Pydantic sees anything;
- ``ttl_seconds`` with no upper bound. Past 251 616 310 632 the addition to
  ``datetime.now()`` raises ``OverflowError``, which is not a
  ``ValueError``, so every handler on the way out missed it;
- no ``Content-Type``. Flask raises 415 for that, and the catch-all handler
  swallowed it along with real crashes and answered 500.

A 500 is not merely an untidy status here: it says the service broke over a
request it should have refused, it puts the request in error monitoring, and
it tells the client the call is worth retrying.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from tests.integration.conftest import auth_headers, csrf_headers


_addresses = itertools.count(1)


def _url():
    """A URL nothing else in the session has shortened."""
    return f"https://example.com/{uuid.uuid4().hex}"


def _post(client, path, **kwargs):
    """
    POST as an anonymous caller.

    Every call arrives from an address of its own: both the guest quota and
    the rate limiter are per-address, and a test that shares one measures
    them instead of what it came to measure.
    """
    number = next(_addresses)
    address = f"198.18.{number // 256 % 256}.{number % 256}"
    return client.post(
        path,
        headers=csrf_headers(client),
        environ_base={"REMOTE_ADDR": address},
        **kwargs,
    )


class TestABodyThatIsNotAnObject:
    """``[1, 2]``, ``"text"``, ``5`` and ``true`` are all valid JSON."""

    @pytest.mark.parametrize("body", [[1, 2], "text", 5, True, [{"url": "x"}]])
    @pytest.mark.parametrize("path", ["/api/v1/shorten", "/api/v1/batch/shorten"])
    def test_it_is_refused_with_400(self, client, path, body):
        response = _post(client, path, json=body)

        assert response.status_code == 400, response.get_json()

    @pytest.mark.parametrize("path", ["/api/v1/shorten", "/api/v1/batch/shorten"])
    def test_an_empty_body_still_reports_the_missing_field(self, client, path):
        """Absent is not malformed: the caller should hear which field is missing."""
        response = _post(client, path, json={})

        assert response.status_code == 400
        assert response.get_json()["error"] == "VALIDATION_ERROR"

    def test_a_well_formed_body_still_works(self, client):
        response = _post(client, "/api/v1/shorten", json={"url": _url()})

        assert response.status_code == 201, response.get_json()


class TestTheAdminSurfaceAnswersTheSameWayAboutAShape:
    """
    Three doors read the body; two of them went through the guard.

    ``web/request_body.json_object`` exists because ``**`` on a list
    raises ``TypeError`` before Pydantic is reached, and the class above
    holds the two public creation endpoints to it. The admin controller
    read ``request.get_json() or {}`` at four sites instead, so one API
    answered a malformed body two ways -- 400 with a named field from
    every public route, 500 from the administrative ones. A 500 also
    files the refusal in error monitoring next to real crashes.

    Behind a permission, so the shape is asked about by a caller who is
    allowed through the door: a 401 would pass a check like this without
    ever reaching the body.
    """

    @pytest.fixture()
    def administrator(self, app):
        """A client holding the two permissions these routes ask for."""
        from tests.integration.conftest import account_with_permissions

        return account_with_permissions(
            app,
            f"admin-shape-{uuid.uuid4().hex[:8]}@example.com",
            "Str0ng!Passw0rd",
            f"shape-admin-{uuid.uuid4().hex[:6]}",
            ["admin:manage_users", "admin:manage_roles"],
        )

    @pytest.mark.parametrize("body", [[1, 2], "text", 5, True])
    @pytest.mark.parametrize("path", [
        "/api/v1/admin/users",
        "/api/v1/admin/roles",
    ])
    def test_a_body_that_is_not_an_object_is_refused_with_400(
        self, administrator, path, body
    ):
        client, token, _user_id = administrator

        answer = client.post(
            path, json=body, headers=csrf_headers(client, auth_headers(token))
        )

        assert answer.status_code == 400, (
            f"{path} answered {answer.status_code} to {body!r}: "
            f"{answer.get_data(as_text=True)[:200]}"
        )

    @pytest.mark.parametrize("path", [
        "/api/v1/admin/users",
        "/api/v1/admin/roles",
    ])
    def test_the_refusal_names_the_body(self, administrator, path):
        """
        The same sentence the public routes give, so a client reading one
        API does not have to learn two vocabularies for one mistake.
        """
        client, token, _user_id = administrator

        answer = client.post(
            path, json=[1, 2],
            headers=csrf_headers(client, auth_headers(token)),
        )

        assert "JSON object" in answer.get_data(as_text=True), (
            answer.get_data(as_text=True)[:200]
        )

    def test_a_well_formed_body_still_works(self, administrator):
        """
        The other half: the guard must not refuse what it is there to let
        through.
        """
        client, token, _user_id = administrator

        answer = client.post(
            "/api/v1/admin/roles",
            json={
                "name": f"shape-ok-{uuid.uuid4().hex[:6]}",
                "description": "created past the shape guard",
                # Not empty, and not anything: a role must carry at least
                # one permission, and an actor may only confer what it
                # holds. Registration grants this one.
                "permissions": ["link:create"],
            },
            headers=csrf_headers(client, auth_headers(token)),
        )

        assert answer.status_code == 201, answer.get_data(as_text=True)


class TestAMissingContentType:
    """Flask's own refusal, answered as a refusal rather than a crash."""

    @pytest.mark.parametrize(
        "path", ["/api/v1/shorten", "/api/v1/batch/shorten"]
    )
    def test_it_is_reported_as_415(self, client, path):
        response = _post(client, path, data="url=https://example.com/x")

        assert response.status_code == 415, response.get_json()

    def test_login_answers_the_same_415(self, client):
        """
        The auth routes read the body the same way as everything else now.

        They used to parse it silently and answer 400 on their own, so 415
        never reached a handler and a form submission was reported as
        credentials nobody sent -- the fields were there, the encoding was
        not. This test was written to make that show up if the parsing
        changed, and this is it changing: one reader in
        ``web/request_body.py``, one answer for one request.
        """
        response = _post(client, "/api/v1/auth/login", data="email=a@b.c")

        assert response.status_code == 415, response.get_json()

    def test_the_answer_is_still_json_for_an_api_path(self, client):
        response = _post(client, "/api/v1/shorten", data="not json")

        assert response.is_json
        assert response.get_json()["error"] == "UNSUPPORTED_MEDIA_TYPE"

    def test_malformed_json_is_still_400(self, client):
        response = _post(
            client,
            "/api/v1/shorten",
            data="{not json",
            content_type="application/json",
        )

        assert response.status_code == 400


class TestTheLifetimeAskedFor:
    """``ttl_seconds`` is bounded now, and bounded twice for a guest."""

    def test_a_number_too_large_to_be_a_date_is_refused(self, client):
        response = _post(
            client,
            "/api/v1/shorten",
            json={"url": _url(), "ttl_seconds": 10 ** 12},
        )

        assert response.status_code == 400, response.get_json()

    def test_the_exact_boundary_of_the_old_crash_is_refused(self, client):
        """251 616 310 632 was where ``timedelta`` gave up."""
        response = _post(
            client,
            "/api/v1/shorten",
            json={"url": _url(), "ttl_seconds": 251_616_310_632},
        )

        assert response.status_code == 400, response.get_json()

    def test_an_ordinary_lifetime_is_granted(self, client):
        response = _post(
            client, "/api/v1/shorten", json={"url": _url(), "ttl_seconds": 3600}
        )

        assert response.status_code == 201, response.get_json()

    def test_a_guest_cannot_outlive_the_guest_lifetime(self, client, app):
        """
        The guest TTL was applied only when nothing was asked for, so asking
        for something bought a guest a link for decades -- which is the whole
        of what a guest lifetime exists to prevent.
        """
        ceiling = app.config["DEFAULT_GUEST_TTL_SECONDS"]
        response = _post(
            client,
            "/api/v1/shorten",
            json={"url": _url(), "ttl_seconds": 10 ** 8},
        )

        assert response.status_code == 201, response.get_json()

        expires_at = datetime.fromisoformat(response.get_json()["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        latest = datetime.now(timezone.utc) + timedelta(seconds=ceiling + 60)

        assert expires_at <= latest

    def test_a_guest_asking_for_less_still_gets_less(self, client):
        """A ceiling, not a replacement: a shorter request is honoured."""
        response = _post(
            client, "/api/v1/shorten", json={"url": _url(), "ttl_seconds": 60}
        )

        expires_at = datetime.fromisoformat(response.get_json()["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        assert expires_at <= datetime.now(timezone.utc) + timedelta(seconds=120)


class TestAStatusThatMatchesWhatHappened:
    """
    One condition, one status.

    A short code that cannot exist and a short code nobody has taken are
    the same answer -- there is no such link -- and the API gave three:
    ``GET /nope`` said 400, ``GET /abcdefg`` said 404, and ``DELETE`` said
    404 for both, because it happened to swallow the error. On the redirect
    route, which catches every unmatched path, 400 also meant the service
    called a page that does not exist a bad request.
    """

    @pytest.mark.parametrize("code", ["nope", "abcdefg", "with space", "x" * 60])
    def test_the_redirect_route_answers_404(self, client, code):
        assert client.get(f"/{code}").status_code == 404

    @pytest.mark.parametrize("code", ["nope", "abcdefg"])
    def test_the_info_endpoint_answers_404(self, client, code):
        assert client.get(f"/api/v1/links/{code}").status_code == 404

    @pytest.mark.parametrize("code", ["nope", "abcdefg"])
    def test_the_extended_endpoint_answers_404(self, client, code):
        assert client.get(f"/api/v1/links/{code}/extended").status_code == 404

    def test_deleting_one_answers_404_as_it_always_did(self, client):
        response = client.delete(
            "/api/v1/links/nope", headers=csrf_headers(client)
        )

        assert response.status_code == 404

    def test_a_deeply_nested_body_is_refused_rather_than_survived(self, client):
        """
        Ten thousand nested brackets exhaust the decoder's stack, and
        ``RecursionError`` is not a ``ValueError`` -- so Werkzeug did not
        turn it into 400 and it reached the catch-all as a 500, on every
        endpoint that reads a body, without authentication.
        """
        response = _post(
            client,
            "/api/v1/shorten",
            data="[" * 10000 + "]" * 10000,
            content_type="application/json",
        )

        assert response.status_code == 400, response.get_json()

    @pytest.mark.parametrize(
        "path", ["/api/v1/batch/shorten", "/api/v1/auth/login"]
    )
    def test_the_same_body_is_refused_on_the_other_endpoints(self, client, path):
        # Brackets, not braces: ``"{" * 10000`` is refused by the decoder on
        # the second character, before it can recurse at all, so it would
        # have tested nothing.
        response = _post(
            client,
            path,
            data="[" * 10000 + "]" * 10000,
            content_type="application/json",
        )

        assert response.status_code < 500, response.get_json()

    def test_the_service_still_works_afterwards(self, client):
        response = _post(client, "/api/v1/shorten", json={"url": _url()})

        assert response.status_code == 201


class TestOneReaderMeansOneAnswer:
    """The same broken body gets the same sentence on every route.

    Two controllers each carried a private body reader, and the two
    disagreed. Ten thousand nested brackets were named on the API routes --
    "Request body is nested too deeply" -- and reported on the auth routes
    as credentials nobody sent, which sends a person to re-type fields
    they had already typed.
    """

    DEEP = "[" * 10000 + "]" * 10000

    @pytest.mark.parametrize("path", [
        "/api/v1/shorten",
        "/api/v1/batch/shorten",
        "/api/v1/auth/login",
        "/api/v1/auth/register",
        "/api/v1/auth/forgot-password",
        "/api/v1/auth/reset-password",
    ])
    def test_a_body_too_deep_to_decode_is_named_as_that(self, client, path):
        response = _post(
            client, path, data=self.DEEP, content_type="application/json"
        )

        assert response.status_code == 400, response.get_json()
        body = response.get_json()
        assert body["error"] == "VALIDATION_ERROR"
        assert body["message"] == "Request body is nested too deeply"
        assert body["details"][0]["field"] == "body"

    @pytest.mark.parametrize("path", [
        "/api/v1/shorten",
        "/api/v1/auth/login",
        "/api/v1/auth/register",
    ])
    def test_a_body_of_literal_null_reads_as_no_body(self, client, path):
        """``null`` is valid JSON and decodes to nothing.

        It is the one value that reaches the reader as ``None`` -- an
        absent body is refused earlier, by Flask, for not being offered
        as JSON. Treated as an object it would be ``None.get(...)``, and
        the endpoint would answer 500 to an unauthenticated caller.
        """
        response = _post(
            client, path, data="null", content_type="application/json"
        )

        assert response.status_code == 400, response.get_json()
        # The fields it did not send, rather than a complaint about the
        # body: nothing was sent, so nothing about it is malformed.
        assert response.get_json()["error"] == "VALIDATION_ERROR"

    @pytest.mark.parametrize("path", [
        "/api/v1/shorten",
        "/api/v1/auth/login",
        "/api/v1/auth/register",
    ])
    def test_a_body_that_is_not_an_object_is_named_as_that(self, client, path):
        response = _post(client, path, json=[1, 2, 3])

        assert response.status_code == 400, response.get_json()
        body = response.get_json()
        assert body["error"] == "VALIDATION_ERROR"
        assert body["message"] == "Request body must be a JSON object"


class TestTheRoutesThatNeedNoBody:
    """Signing out and refreshing read a cookie, and may carry nothing.

    Read as strictly as the rest, a sign-out with no body would be
    answered 415 -- Flask refuses a body that is not offered as JSON, and
    a body that is not there is not offered. Both routes take their token
    from the cookie first, so arriving without one is ordinary.
    """

    def test_signing_out_without_a_body_is_not_a_media_type_error(self, client):
        response = _post(client, "/api/v1/auth/logout")

        assert response.status_code == 200, response.get_json()

    def test_refreshing_without_a_body_says_the_token_is_missing(self, client):
        response = _post(client, "/api/v1/auth/refresh")

        assert response.status_code == 401, response.get_json()
        assert response.get_json()["error"] == "UNAUTHENTICATED"

    @pytest.mark.parametrize("path, status", [
        ("/api/v1/auth/logout", 200),
        ("/api/v1/auth/refresh", 401),
    ])
    def test_a_json_header_over_an_empty_body_is_still_no_body(
        self, client, path, status
    ):
        """The shape this application's own pages send.

        ``apiFetch`` puts ``Content-Type: application/json`` on every
        request it makes and sends no body with a sign-out. Read strictly
        that is a malformed JSON document -- nought bytes where an object
        was promised -- and the route answered 400 "Malformed request
        body". A browser never saw it, because a browser has the cookie
        and returns before the body is read; a client without one did.
        """
        response = _post(client, path, data="", content_type="application/json")

        assert response.status_code == status, response.get_json()

    def test_a_body_that_is_offered_as_json_is_still_read_strictly(self, client):
        response = _post(
            client,
            "/api/v1/auth/refresh",
            data="[" * 10000 + "]" * 10000,
            content_type="application/json",
        )

        assert response.status_code == 400, response.get_json()
        assert response.get_json()["message"] == (
            "Request body is nested too deeply"
        )
