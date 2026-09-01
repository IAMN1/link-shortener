"""Integration tests for CsrfProtectionMiddleware with real DB."""

import pytest

from link_shortener.web.middleware.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME
from tests.integration.conftest import confirm_email, auth_headers, csrf_headers


def _login(client, email, password="StrongPass1!"):
    """
    Register and log in, leaving the session cookies in the client jar.

    Args:
        client: Flask test client.
        email: Email to register.
        password: Password to register with.

    Returns:
        The access token from the response body.
    """
    client.post("/api/v1/auth/register", json={
        "email": email, "password": password
    })
    confirm_email(client.application, email)
    r = client.post("/api/v1/auth/login", json={
        "email": email, "password": password
    })
    assert r.status_code == 200
    return r.get_json()["access_token"]


class TestCsrfCookieIssuing:
    """The token has to reach the browser to be echoed back."""

    def test_login_sets_readable_csrf_cookie(self, app):
        client = app.test_client()
        r = client.post("/api/v1/auth/register", json={
            "email": "csrfissue@example.com", "password": "StrongPass1!"
        })
        confirm_email(client.application, "csrfissue@example.com")
        r = client.post("/api/v1/auth/login", json={
            "email": "csrfissue@example.com", "password": "StrongPass1!"
        })

        assert client.get_cookie(CSRF_COOKIE_NAME) is not None

        # The frontend must be able to read it, so unlike the auth cookies
        # this one is deliberately not HttpOnly.
        csrf_header = next(
            h for h in r.headers.getlist("Set-Cookie")
            if h.startswith(f"{CSRF_COOKIE_NAME}=")
        )
        assert "HttpOnly" not in csrf_header
        assert "SameSite=Strict" in csrf_header

    def test_logout_clears_csrf_cookie(self, app):
        client = app.test_client()
        _login(client, "csrflogout@example.com")

        client.post("/api/v1/auth/logout", headers=csrf_headers(client))
        cookie = client.get_cookie(CSRF_COOKIE_NAME)
        # Deleted, not emptied. `or cookie.value == ""` accepted both, so
        # the test could not say which of the two the logout actually does.
        assert cookie is None

    def test_write_without_csrf_cookie_recovers_on_retry(self, app):
        client = app.test_client()
        _login(client, "csrfstalesession@example.com")

        # A session that predates CSRF protection: auth cookies, no token.
        client.delete_cookie(CSRF_COOKIE_NAME, path="/")

        rejected = client.post("/api/v1/auth/logout")
        assert rejected.status_code == 403

        # The rejection itself hands out a token, so the retry goes through
        # instead of stranding the session.
        assert client.get_cookie(CSRF_COOKIE_NAME) is not None
        retried = client.post("/api/v1/auth/logout", headers=csrf_headers(client))
        assert retried.status_code == 200

    def test_unverifiable_cookie_is_replaced_not_left_to_rot(self, app):
        client = app.test_client()
        _login(client, "csrfstaletoken@example.com")

        # A token this session cannot use: left over from another account,
        # or from an older token format.
        client.set_cookie(CSRF_COOKIE_NAME, "stale.value", path="/")

        rejected = client.post(
            "/api/v1/shorten", json={"url": "https://example.com/csrf-stale"}
        )
        assert rejected.status_code == 403

        # Without renewal here the session would fail every write from now
        # on, with nothing to recover it.
        assert client.get_cookie(CSRF_COOKIE_NAME).value != "stale.value"
        retried = client.post(
            "/api/v1/shorten",
            json={"url": "https://example.com/csrf-stale-retry"},
            headers=csrf_headers(client),
        )
        assert retried.status_code == 201

    def test_session_without_csrf_cookie_is_reissued_one(self, app):
        client = app.test_client()
        _login(client, "csrfreissue@example.com")

        # Simulate a session established before CSRF protection existed.
        client.delete_cookie(CSRF_COOKIE_NAME, path="/")
        assert client.get_cookie(CSRF_COOKIE_NAME) is None

        client.get("/api/v1/links/mine")
        assert client.get_cookie(CSRF_COOKIE_NAME) is not None


class TestCsrfEnforcement:
    """Cookie-authenticated writes require a matching token."""

    def test_cookie_auth_write_without_token_is_rejected(self, app):
        client = app.test_client()
        _login(client, "csrfnotoken@example.com")

        r = client.post(
            "/api/v1/shorten", json={"url": "https://example.com/csrf-1"}
        )
        assert r.status_code == 403
        assert r.get_json()["error"] == "CSRF_TOKEN_INVALID"

    def test_cookie_auth_write_with_token_is_allowed(self, app):
        client = app.test_client()
        _login(client, "csrfok@example.com")

        r = client.post(
            "/api/v1/shorten",
            json={"url": "https://example.com/csrf-2"},
            headers=csrf_headers(client),
        )
        assert r.status_code == 201

    def test_cookie_auth_write_with_wrong_token_is_rejected(self, app):
        client = app.test_client()
        _login(client, "csrfwrong@example.com")

        r = client.post(
            "/api/v1/shorten",
            json={"url": "https://example.com/csrf-3"},
            headers={CSRF_HEADER_NAME: "not-the-right-token"},
        )
        assert r.status_code == 403

    def test_cookie_auth_delete_without_token_is_rejected(self, app):
        client = app.test_client()
        _login(client, "csrfdelete@example.com")

        created = client.post(
            "/api/v1/shorten",
            json={"url": "https://example.com/csrf-4"},
            headers=csrf_headers(client),
        )
        code = created.get_json()["short_code"]

        r = client.delete(f"/api/v1/links/{code}")
        assert r.status_code == 403

    def test_safe_method_needs_no_token(self, app):
        client = app.test_client()
        _login(client, "csrfsafe@example.com")

        r = client.get("/api/v1/links/mine")
        assert r.status_code == 200


class TestTokenSignature:
    """A matching pair is not enough; the token has to be one we issued."""

    def test_self_chosen_token_is_refused(self, app):
        client = app.test_client()
        _login(client, "csrfplanted@example.com")

        # What an attacker able to write a cookie on the domain would do:
        # plant a known value and echo it back. Plain double submit accepts
        # this, because both copies agree.
        planted = "attacker-chosen-value"
        client.set_cookie(CSRF_COOKIE_NAME, planted, path="/")

        r = client.post(
            "/api/v1/shorten",
            json={"url": "https://example.com/csrf-planted"},
            headers={CSRF_HEADER_NAME: planted},
        )
        assert r.status_code == 403

    def test_token_of_another_user_is_refused(self, app):
        other = app.test_client()
        other.post("/api/v1/auth/register", json={
            "email": "csrfother@example.com", "password": "StrongPass1!"
        })
        confirm_email(other.application, "csrfother@example.com")
        r = other.post("/api/v1/auth/login", json={
            "email": "csrfother@example.com", "password": "StrongPass1!"
        })
        foreign = other.get_cookie(CSRF_COOKIE_NAME).value

        victim = app.test_client()
        _login(victim, "csrfmine@example.com")
        victim.set_cookie(CSRF_COOKIE_NAME, foreign, path="/")

        # Signed, but for somebody else.
        r = victim.post(
            "/api/v1/shorten",
            json={"url": "https://example.com/csrf-foreign"},
            headers={CSRF_HEADER_NAME: foreign},
        )
        assert r.status_code == 403


class TestOriginCheck:
    """A browser-stated origin has to be one we serve."""

    def test_foreign_origin_is_refused(self, app):
        client = app.test_client()
        _login(client, "csrforigin@example.com")

        r = client.post(
            "/api/v1/shorten",
            json={"url": "https://example.com/csrf-origin"},
            headers=csrf_headers(client, {"Origin": "https://evil.example"}),
        )
        assert r.status_code == 403

    def test_own_origin_is_allowed(self, app):
        client = app.test_client()
        _login(client, "csrfownorigin@example.com")

        r = client.post(
            "/api/v1/shorten",
            json={"url": "https://example.com/csrf-own-origin"},
            headers=csrf_headers(client, {"Origin": "http://testserver"}),
        )
        assert r.status_code == 201

    def test_foreign_referer_is_refused(self, app):
        client = app.test_client()
        _login(client, "csrfreferer@example.com")

        r = client.post(
            "/api/v1/shorten",
            json={"url": "https://example.com/csrf-referer"},
            headers=csrf_headers(
                client, {"Referer": "https://evil.example/page"}
            ),
        )
        assert r.status_code == 403

    def test_missing_origin_falls_back_to_the_signed_token(self, app):
        client = app.test_client()
        _login(client, "csrfnoorigin@example.com")

        # Proxies do strip these headers, so their absence must not break a
        # legitimate request that carries a properly signed token.
        r = client.post(
            "/api/v1/shorten",
            json={"url": "https://example.com/csrf-no-origin"},
            headers=csrf_headers(client),
        )
        assert r.status_code == 201


class TestCsrfExemptions:
    """Requests that cannot be forged cross-site are left alone."""

    def test_bearer_auth_write_needs_no_token(self, app):
        login_client = app.test_client()
        token = _login(login_client, "csrfbearer@example.com")

        # A client that can set the Authorization header is not a browser
        # being driven by a third-party site.
        api_client = app.test_client()
        r = api_client.post(
            "/api/v1/shorten",
            json={"url": "https://example.com/csrf-5"},
            headers=auth_headers(token),
        )
        assert r.status_code == 201

    def test_empty_bearer_does_not_buy_an_exemption(self, app):
        client = app.test_client()
        _login(client, "csrfemptybearer@example.com")

        created = client.post(
            "/api/v1/shorten",
            json={"url": "https://example.com/csrf-7"},
            headers=csrf_headers(client),
        )
        code = created.get_json()["short_code"]

        # "Bearer " with nothing after it is not a header credential: the
        # request still authenticates on the cookie, so it must still be
        # asked for a CSRF token.
        r = client.delete(
            f"/api/v1/links/{code}", headers={"Authorization": "Bearer "}
        )
        assert r.status_code == 403

    @pytest.mark.parametrize(
        "label,header_value",
        [
            ("empty", "Bearer "),
            ("spaces", "Bearer  "),
            ("tab", "Bearer\t"),
            ("lowercase", "bearer "),
            ("bare", "Bearer"),
        ],
    )
    def test_malformed_authorization_header_never_acts_as_the_user(
        self, app, label, header_value
    ):
        """
        A header that is not a usable credential must never let a write
        through on the victim's authority. Depending on the exact shape it
        either falls back to the cookie (and owes a CSRF token) or leaves
        the request anonymous -- but never both exempt and authenticated.
        """
        client = app.test_client()
        _login(client, f"csrfmalformed-{label}@example.com")

        created = client.post(
            "/api/v1/shorten",
            json={"url": f"https://example.com/csrf-malformed-{label}"},
            headers=csrf_headers(client),
        )
        code = created.get_json()["short_code"]

        r = client.delete(
            f"/api/v1/links/{code}", headers={"Authorization": header_value}
        )
        # Deliberately loose, unlike the rest of this file. The docstring
        # above says either branch is acceptable, and it means it: a shape
        # that falls back to the cookie owes a CSRF token and gets 403, one
        # that leaves the request anonymous gets 401. The invariant under
        # test is that neither ends up exempt *and* authenticated, and that
        # is what `still_there` below checks. Pinning one code here would
        # forbid a routing change the security property allows.
        assert r.status_code in (401, 403)

        # The link is still there, which is what actually matters.
        still_there = client.get("/api/v1/links/mine", headers=csrf_headers(client))
        assert code in [link["short_code"] for link in still_there.get_json()]

    @pytest.mark.parametrize(
        "label,header_value",
        [("garbage", "Bearer nonsense.not.a.token"), ("empty", "Bearer ")],
    )
    def test_refresh_is_never_exempted_by_a_header(self, app, label, header_value):
        """
        ``/auth/refresh`` spends the refresh cookie whatever the headers say,
        so a header credential must not excuse it from CSRF. Otherwise a
        throwaway Authorization value turns the victim's refresh cookie into
        a fresh access token for their account.

        Loose about which refusal, for the reason the sweep above gives:
        the two shapes are refused by different doors. ``Bearer `` with
        nothing after it is no credential at all, falls back to the cookie
        and owes a CSRF token -- 403. ``Bearer nonsense.not.a.token`` is a
        credential the caller chose to present and the service now refuses
        it outright -- 401, before CSRF is reached. The invariant is the
        line below: neither shape comes back with a token.
        """
        victim = app.test_client()
        _login(victim, f"csrfrefresh-{label}@example.com")

        r = victim.post(
            "/api/v1/auth/refresh", headers={"Authorization": header_value}
        )
        assert r.status_code in (401, 403)
        assert "access_token" not in (r.get_json() or {})

    def test_refresh_with_a_valid_foreign_token_is_still_checked(self, app):
        """A real token belonging to someone else is no excuse either."""
        attacker = app.test_client()
        attacker_token = _login(attacker, "csrfattacker@example.com")

        victim = app.test_client()
        _login(victim, "csrfvictim@example.com")

        r = victim.post(
            "/api/v1/auth/refresh", headers=auth_headers(attacker_token)
        )
        assert r.status_code == 403

    def test_logout_is_never_exempted_by_a_header(self, app):
        """
        ``/auth/logout`` revokes the session named by the refresh cookie, so
        like refresh it acts on cookie authority and a header credential is
        no excuse. Getting through would let someone force a victim's
        session closed.
        """
        attacker = app.test_client()
        attacker_token = _login(attacker, "csrflogoutattacker@example.com")

        victim = app.test_client()
        _login(victim, "csrflogoutvictim@example.com")

        r = victim.post(
            "/api/v1/auth/logout", headers=auth_headers(attacker_token)
        )
        assert r.status_code == 403

        # The victim's session is untouched: it can still be refreshed.
        assert victim.post(
            "/api/v1/auth/refresh", headers=csrf_headers(victim)
        ).status_code == 200

    def test_refresh_still_works_for_the_real_browser_flow(self, app):
        client = app.test_client()
        _login(client, "csrfrefreshok@example.com")

        r = client.post("/api/v1/auth/refresh", headers=csrf_headers(client))
        assert r.status_code == 200
        assert r.get_json()["access_token"]

    def test_unvalidated_bearer_token_grants_no_exemption(self, app):
        """
        The exemption belongs to the credential that actually authenticated
        the request. A Bearer token that fails validation authenticates
        nothing, so it buys no exemption -- and since the service began
        refusing a presented credential it cannot verify, it does not even
        reach CSRF: the refusal is 401 rather than 403.

        Which of the two is not the property. The property is that the
        write does not happen, and that is asserted below rather than left
        to a status code, so a later change of door cannot quietly turn
        this into a test of nothing.
        """
        client = app.test_client()
        _login(client, "csrfbadbearer@example.com")

        r = client.post(
            "/api/v1/shorten",
            json={"url": "https://example.com/csrf-9"},
            headers={"Authorization": "Bearer not.a.valid.token"},
        )
        assert r.status_code in (401, 403)

        made = client.get("/api/v1/links/mine", headers=csrf_headers(client))
        assert "https://example.com/csrf-9" not in [
            link["original_url"] for link in made.get_json()
        ]

    def test_token_resolving_to_nobody_grants_no_exemption(self, app, db):
        """
        A token can be perfectly valid and still authenticate no one, once
        the account behind it is gone. The exemption tracks the authenticated
        user, not the signature.
        """
        holder = app.test_client()
        holder_token = _login(holder, "csrfdeactivated@example.com")

        from tests.integration.web.middleware.test_authentication import (
            _deactivate_user,
        )
        _deactivate_user(db, "csrfdeactivated@example.com")

        victim = app.test_client()
        _login(victim, "csrfdeactvictim@example.com")

        r = victim.post(
            "/api/v1/shorten",
            json={"url": "https://example.com/csrf-10"},
            headers=auth_headers(holder_token),
        )
        # 401 now: a token whose account is gone is a credential the caller
        # presented and the service cannot honour, so it is refused before
        # CSRF is asked about. It used to fall through to the cookie and be
        # refused there instead. Neither writes, which is the property.
        assert r.status_code in (401, 403)

        made = victim.get("/api/v1/links/mine", headers=csrf_headers(victim))
        assert "https://example.com/csrf-10" not in [
            link["original_url"] for link in made.get_json()
        ]

    def test_non_ascii_token_is_refused_not_crashed(self, app):
        client = app.test_client()
        _login(client, "csrfnonascii@example.com")

        r = client.post(
            "/api/v1/shorten",
            json={"url": "https://example.com/csrf-8"},
            headers={CSRF_HEADER_NAME: "ÿÿ"},
        )
        assert r.status_code == 403

    def test_anonymous_write_needs_no_token(self, app):
        client = app.test_client()
        r = client.post(
            "/api/v1/shorten", json={"url": "https://example.com/csrf-6"}
        )
        assert r.status_code == 201

    def test_login_is_not_blocked_for_a_returning_session(self, app):
        client = app.test_client()
        _login(client, "csrfrelogin@example.com")

        # Logging in again while the previous session cookies are still set
        # must not be mistaken for a forged request.
        r = client.post(
            "/api/v1/auth/login",
            json={"email": "csrfrelogin@example.com", "password": "StrongPass1!"},
            headers=csrf_headers(client),
        )
        assert r.status_code == 200


class TestTheRefusalIsAnAnswerLikeAnyOther:
    """A blocked write is read by a person, in the language of the page.

    The refusal used to be assembled here rather than through
    ``error_response``, and its sentence was "CSRF token missing or
    invalid" -- the name of the mechanism, in English, whatever language
    the same request had just been answered in. Both halves of that are
    what these hold.
    """

    def test_the_envelope_is_the_one_every_other_refusal_uses(self, app):
        client = app.test_client()
        _login(client, "csrfenvelope@example.com")

        r = client.post(
            "/api/v1/shorten", json={"url": "https://example.com/csrf-env"}
        )

        assert r.status_code == 403
        body = r.get_json()
        assert {"error", "message", "details", "timestamp"} <= set(body)
        assert body["error"] == "CSRF_TOKEN_INVALID"

    def test_the_sentence_is_in_the_language_of_the_request(self, app):
        client = app.test_client()
        _login(client, "csrflang@example.com")
        client.set_cookie("lang", "ru", domain="localhost")

        r = client.post(
            "/api/v1/shorten", json={"url": "https://example.com/csrf-lang"}
        )

        assert r.status_code == 403
        message = r.get_json()["message"]
        assert message == (
            "Этот запрос не удалось проверить. Обновите страницу и повторите."
        )

    def test_the_sentence_names_no_machinery(self, app):
        """What a visitor is told is what they can do about it.

        "CSRF" and "token" are the names of the check, and a person who
        left a form open for half a day cannot act on either.
        """
        client = app.test_client()
        _login(client, "csrfplain@example.com")

        r = client.post(
            "/api/v1/shorten", json={"url": "https://example.com/csrf-plain"}
        )

        message = r.get_json()["message"].lower()
        assert "csrf" not in message
        assert "token" not in message
