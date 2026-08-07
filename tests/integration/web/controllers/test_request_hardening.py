"""
Tests that a malformed request is refused rather than survived.

Three ways an anonymous caller used to get a 500 out of the two creation
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

from tests.integration.conftest import csrf_headers


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


class TestAMissingContentType:
    """Flask's own refusal, which used to be reported as a crash."""

    @pytest.mark.parametrize(
        "path", ["/api/v1/shorten", "/api/v1/batch/shorten"]
    )
    def test_it_is_reported_as_415(self, client, path):
        response = _post(client, path, data="url=https://example.com/x")

        assert response.status_code == 415, response.get_json()

    def test_login_answers_for_itself(self, client):
        """
        The auth controller parses the body silently and answers 400 on its
        own, so 415 never reaches a handler here. Asserted so that a change
        to silent parsing shows up as this test rather than as a 500.
        """
        response = _post(client, "/api/v1/auth/login", data="email=a@b.c")

        assert response.status_code == 400, response.get_json()

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

        assert response.status_code in (401, 404)

    def test_a_deeply_nested_body_is_refused_rather_than_survived(self, client):
        """
        Twenty kilobytes of ``[`` exhausts the decoder's stack, and
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
