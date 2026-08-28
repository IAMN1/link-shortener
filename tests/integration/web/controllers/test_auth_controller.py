"""Integration tests for auth endpoints with real DB."""

import pytest
from tests.integration.conftest import (
    auth_headers, confirm_email, csrf_headers
)



def _without_timestamp(response) -> dict:
    """
    The body of an error answer, minus the moment it was made.

    Args:
        response: The Flask test-client response to read.

    Returns:
        The JSON body without its ``timestamp`` field, so that two answers
        can be compared for what they say rather than for when.
    """
    body = dict(response.get_json())
    body.pop("timestamp", None)
    return body

class TestRegister:
    """POST /api/v1/auth/register"""

    def test_register_success(self, client):
        r = client.post("/api/v1/auth/register", json={
            "email": "new@example.com", "password": "StrongPass1!"
        })
        assert r.status_code == 202
        data = r.get_json()
        # No tokens, so signing up does not sign you in -- and no account
        # either, because an identifier here would be the answer to
        # "is this address registered" that the status no longer gives.
        assert "user" not in data
        assert "access_token" not in data

    def test_register_duplicate_email(self, client):
        client.post("/api/v1/auth/register", json={
            "email": "dup@example.com", "password": "StrongPass1!"
        })
        r = client.post("/api/v1/auth/register", json={
            "email": "dup@example.com", "password": "StrongPass1!"
        })
        assert r.status_code == 202

    def test_register_weak_password(self, client):
        r = client.post("/api/v1/auth/register", json={
            "email": "weak@example.com", "password": "123"
        })
        assert r.status_code == 400

    def test_register_missing_fields(self, client):
        r = client.post("/api/v1/auth/register", json={})
        assert r.status_code == 400

    def test_register_bad_email(self, client):
        r = client.post("/api/v1/auth/register", json={
            "email": "not-email", "password": "StrongPass1!"
        })
        assert r.status_code == 400


class TestLogin:
    """POST /api/v1/auth/login"""

    def test_login_success(self, client):
        client.post("/api/v1/auth/register", json={
            "email": "login@example.com", "password": "StrongPass1!"
        })
        confirm_email(client.application, "login@example.com")
        r = client.post("/api/v1/auth/login", json={
            "email": "login@example.com", "password": "StrongPass1!"
        })
        assert r.status_code == 200
        data = r.get_json()
        assert "access_token" in data

    def test_login_wrong_password(self, client):
        client.post("/api/v1/auth/register", json={
            "email": "lpw@example.com", "password": "StrongPass1!"
        })
        r = client.post("/api/v1/auth/login", json={
            "email": "lpw@example.com", "password": "wrong"
        })
        assert r.status_code == 401

    def test_login_nonexistent_user(self, client):
        r = client.post("/api/v1/auth/login", json={
            "email": "ghost@example.com", "password": "StrongPass1!"
        })
        assert r.status_code == 401

    def test_login_missing_fields(self, client):
        r = client.post("/api/v1/auth/login", json={})
        assert r.status_code == 400


class TestErrorDisclosure:
    """Auth endpoints must not describe their internals to the client."""

    OVERLONG_PASSWORD = "A" * 100

    def test_register_rejects_overlong_password_without_leaking(self, client):
        r = client.post("/api/v1/auth/register", json={
            "email": "toolong@example.com", "password": self.OVERLONG_PASSWORD
        })
        assert r.status_code == 400

        # Read from the fields the endpoint writes, not from the whole
        # body: the envelope carries an ISO timestamp, and "72" appears in
        # one whenever the clock says so -- measured at 1.5-5.5% of
        # requests, which made this test fail for reasons having nothing
        # to do with what it checks.
        payload = r.get_json()
        body = " ".join(
            str(payload.get(field, "")) for field in ("error", "message", "details")
        ).lower()

        # Neither bcrypt's own message nor its 72-byte limit, which would
        # point straight at the hashing library.
        assert "bcrypt" not in body
        assert "truncate" not in body
        assert "72" not in body
        assert "byte" not in body
        assert "timestamp" in payload

    def test_invalid_email_is_not_echoed_back(self, client):
        probe = "' OR 1=1--"
        r = client.post("/api/v1/auth/login", json={
            "email": probe, "password": "StrongPass1!"
        })

        assert r.status_code == 400
        assert probe not in r.get_data(as_text=True)

    def test_login_gives_same_answer_for_known_and_unknown_email(self, client):
        client.post("/api/v1/auth/register", json={
            "email": "oracle@example.com", "password": "StrongPass1!"
        })

        known = client.post("/api/v1/auth/login", json={
            "email": "oracle@example.com", "password": self.OVERLONG_PASSWORD
        })
        unknown = client.post("/api/v1/auth/login", json={
            "email": "no-such-user@example.com", "password": self.OVERLONG_PASSWORD
        })

        # Differing answers would let anyone probe which accounts exist.
        # Everything but the timestamp, which the envelope stamps at the
        # moment of the answer and so differs between any two calls; it
        # carries nothing about the account either way.
        assert known.status_code == unknown.status_code == 401
        assert _without_timestamp(known) == _without_timestamp(unknown)


class TestMalformedBody:
    """An odd request body is a client error, never a crash."""

    @pytest.mark.parametrize("body", [42, "a string", [1, 2, 3]])
    def test_non_object_body_is_rejected(self, client, body):
        for path in ("/api/v1/auth/login", "/api/v1/auth/register"):
            r = client.post(path, json=body)
            assert r.status_code == 400, f"{path} with {body!r} → {r.status_code}"

    def test_no_body_at_all_is_the_same_415_the_rest_of_the_api_answers(
        self, client
    ):
        """A request offering no JSON is refused as one, here as elsewhere.

        These routes used to parse the body silently, which turned "you
        sent no JSON" into "you sent no credentials" -- 400 and "Email and
        password are required" to a caller whose fields were fine and
        whose encoding was not. ``POST /api/v1/shorten`` answered 415 to
        the same request throughout. One reader now serves both, in
        ``web/request_body.py``, so there is one answer.
        """
        for path in ("/api/v1/auth/login", "/api/v1/auth/register"):
            r = client.post(path)
            assert r.status_code == 415, f"{path} with no body → {r.status_code}"

    def test_a_body_offered_as_json_but_empty_names_the_missing_fields(
        self, client
    ):
        """``{}`` is a JSON body, so it is read and found wanting."""
        for path in ("/api/v1/auth/login", "/api/v1/auth/register"):
            r = client.post(path, json={})
            assert r.status_code == 400, f"{path} with {{}} → {r.status_code}"
            assert r.get_json()["error"] == "VALIDATION_ERROR"

    @pytest.mark.parametrize(
        "payload",
        [
            {"email": 123, "password": "StrongPass1!"},
            {"email": {"nested": "object"}, "password": "StrongPass1!"},
            {"email": "typed@example.com", "password": ["list"]},
            {"email": None, "password": None},
        ],
    )
    def test_non_string_credentials_are_rejected(self, client, payload):
        for path in ("/api/v1/auth/login", "/api/v1/auth/register"):
            r = client.post(path, json=payload)
            assert r.status_code == 400, f"{path} with {payload!r} → {r.status_code}"

    def test_a_malformed_email_is_a_bad_request_not_a_refusal(self, client):
        """
        Login caught ``DomainError`` whole and answered 401 to all of it,
        and ``ValidationError`` is a ``DomainError``. So "this is not an
        email address" came back as "wrong credentials" -- the same status
        as a wrong password, for an input every other endpoint reports as
        400.
        """
        r = client.post(
            "/api/v1/auth/login",
            json={"email": "not-an-email", "password": "StrongPass1!"},
        )

        assert r.status_code == 400, r.get_json()

    def test_a_wrong_password_is_still_401(self, client):
        """The branch that does mean "refused" keeps its status."""
        client.post(
            "/api/v1/auth/register",
            json={"email": "status@example.com", "password": "StrongPass1!"},
        )

        r = client.post(
            "/api/v1/auth/login",
            json={"email": "status@example.com", "password": "WrongPass1!"},
        )

        assert r.status_code == 401

    def test_a_body_nested_beyond_the_decoder_is_refused(self, client):
        """
        ``"[" * 10000`` nests ten thousand deep and exhausts the
        decoder's stack. ``RecursionError`` is not a ``ValueError``, so
        the silent parse did not swallow it and it reached the catch-all
        as a 500.
        """
        for path in ("/api/v1/auth/login", "/api/v1/auth/register"):
            r = client.post(
                path,
                data="[" * 10000 + "]" * 10000,
                content_type="application/json",
            )
            assert r.status_code < 500, f"{path} → {r.status_code}"


class TestLoginTiming:
    """Response latency must not reveal which accounts exist."""

    def test_unknown_account_is_not_answered_faster(self, client):
        import time

        client.post("/api/v1/auth/register", json={
            "email": "timing@example.com", "password": "StrongPass1!"
        })

        def measure(email):
            samples = []
            for _ in range(3):
                start = time.perf_counter()
                r = client.post("/api/v1/auth/login", json={
                    "email": email, "password": "WrongPass1!"
                })
                samples.append(time.perf_counter() - start)
                assert r.status_code == 401
            return min(samples)

        known = measure("timing@example.com")
        unknown = measure("no-such-account@example.com")

        # Before the decoy hash the gap was ~500x. Anything within an order
        # of magnitude is noise rather than a signal.
        assert unknown > known / 10, (
            f"unknown account answered in {unknown:.4f}s vs {known:.4f}s "
            f"for a known one"
        )


class TestLogout:
    """POST /api/v1/auth/logout"""

    def test_logout(self, client):
        r = client.post("/api/v1/auth/logout")
        assert r.status_code == 200


class TestRefresh:
    """POST /api/v1/auth/refresh"""

    def test_refresh_no_token(self, client):
        r = client.post("/api/v1/auth/refresh", json={})
        assert r.status_code == 401


class TestAuthFlow:
    """Full auth flow: register → login → use token → logout."""

    def test_full_flow(self, client):
        # Register
        r = client.post("/api/v1/auth/register", json={
            "email": "flow@example.com", "password": "StrongPass1!"
        })
        assert r.status_code == 202

        # Confirm the address: registration leaves it unproven, and login
        # refuses an account whose address nobody has confirmed.
        confirm_email(client.application, "flow@example.com")

        # Login
        r = client.post("/api/v1/auth/login", json={
            "email": "flow@example.com", "password": "StrongPass1!"
        })
        assert r.status_code == 200
        token = r.get_json().get("access_token")
        assert token is not None

        # Use token to access protected resource
        headers = auth_headers(token)
        r = client.get("/api/v1/links/mine", headers=headers)
        assert r.status_code == 200

        # Logout
        # The browser holds session cookies here, so logout acts on the
        # cookie and needs the CSRF token to go with it.
        r = client.post("/api/v1/auth/logout", headers=csrf_headers(client, headers))
        assert r.status_code == 200


class TestPasswordStrength:
    """
    Registration accepted ``short``, because the policy bounded only the
    maximum length -- it existed to keep a password inside what bcrypt can
    hash, and nobody had set a floor.
    """

    @pytest.mark.parametrize("password", ["short", "1234567", "a"])
    def test_a_password_below_the_floor_is_refused(self, client, password):
        r = client.post(
            "/api/v1/auth/register",
            json={"email": f"weak-{password}@example.com", "password": password},
        )

        assert r.status_code == 400, r.get_json()

    def test_a_password_from_every_cracking_list_is_refused(self, client):
        r = client.post(
            "/api/v1/auth/register",
            json={"email": "common@example.com", "password": "password123"},
        )

        assert r.status_code == 400, r.get_json()

    def test_an_ordinary_password_still_registers(self, client):
        r = client.post(
            "/api/v1/auth/register",
            json={"email": "strong@example.com", "password": "StrongPass1!"},
        )

        assert r.status_code == 202, r.get_json()

    def test_the_rule_holds_on_the_admin_path_too(self, client, app):
        """
        Every path that sets a password goes through hashing, so none of
        them can be the way around the rule.
        """
        from link_shortener.domain.exceptions import ValidationError

        with app.app_context():
            service = app.container.get_authentication_service()
            with pytest.raises(ValidationError):
                service.hash_password("short")
