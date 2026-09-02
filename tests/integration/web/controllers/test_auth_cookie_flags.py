"""The session cookies come back with their protective flags set.

Nothing checked this. A mutation run turning ``httponly`` off on the refresh
cookie left all 1182 tests green -- the login tests read the JSON body and
never looked at ``Set-Cookie`` at all.

The flags are asserted on the response the client really receives, not on
the configuration that is supposed to produce it: the two have to agree, and
only the response is what a browser acts on.
"""

import pytest

from tests.integration.conftest import confirm_email, csrf_headers


COOKIES = ("access_token", "refresh_token")


def set_cookie_headers(response):
    """Return the Set-Cookie headers of a response, keyed by cookie name.

    Args:
        response: The Flask test response.

    Returns:
        Mapping of cookie name to the raw header value.
    """
    headers = {}
    for key, value in response.headers:
        if key.lower() != "set-cookie":
            continue
        name = value.split("=", 1)[0].strip()
        headers[name] = value
    return headers


@pytest.fixture
def login_response(app):
    """A real login, on a client of its own."""
    client = app.test_client()
    email = "cookie-flags@example.test"
    password = "CookieFlags1!"
    client.post("/api/v1/auth/register", json={"email": email, "password": password})
    confirm_email(client.application, email)
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    return response


class TestLoginCookies:
    """What the browser is told to store, and how."""

    def test_both_tokens_are_set_as_cookies(self, login_response):
        """The control: without these, the assertions below are vacuous."""
        headers = set_cookie_headers(login_response)

        for name in COOKIES:
            assert name in headers, f"{name} was not set at all"

    @pytest.mark.parametrize("name", COOKIES)
    def test_the_cookie_is_httponly(self, login_response, name):
        """A token a script can read is a token XSS can take."""
        header = set_cookie_headers(login_response)[name]

        assert "HttpOnly" in header, f"{name} is readable by scripts: {header}"

    @pytest.mark.parametrize("name", COOKIES)
    def test_the_cookie_is_same_site_strict(self, login_response, name):
        """SameSite is what keeps a cross-site request from carrying it."""
        header = set_cookie_headers(login_response)[name]

        assert "SameSite=Strict" in header, f"{name} lacks SameSite: {header}"

    @pytest.mark.parametrize("name", COOKIES)
    def test_the_cookie_expires(self, login_response, name):
        """A session cookie without a lifetime outlives its token."""
        header = set_cookie_headers(login_response)[name]

        # Max-Age alone. The application only ever passes `max_age`, and
        # Werkzeug derives `Expires` from it, so asserting both would test
        # dump_cookie() rather than this code -- and would break on a
        # Werkzeug change that has nothing to do with cookie lifetimes. The
        # disjunction that stood here was satisfied by either half, which
        # is why it could not say which one the application controls.
        assert "Max-Age=" in header, f"{name} has no Max-Age: {header}"

    @pytest.mark.parametrize("name", COOKIES)
    def test_the_flag_matches_the_configuration(self, app, login_response, name):
        """Secure is set exactly when the configuration asks for it.

        Asserted as agreement rather than as a fixed value: the test profile
        runs without TLS, where a Secure cookie would simply never be sent
        back. What must not happen is the two drifting apart.
        """
        header = set_cookie_headers(login_response)[name]
        expected = bool(app.config.get("COOKIE_SECURE", False))

        assert ("Secure" in header) is expected, (
            f"{name}: COOKIE_SECURE={expected} but header says {header}"
        )


class TestLogoutClearsThem:
    """Ending a session has to end it in the browser too."""

    def test_the_cookies_are_expired_on_logout(self, app):
        """A cookie left behind is a credential left behind."""
        client = app.test_client()
        email = "cookie-logout@example.test"
        password = "CookieLogout1!"
        client.post(
            "/api/v1/auth/register", json={"email": email, "password": password}
        )
        confirm_email(client.application, email)
        client.post("/api/v1/auth/login", json={"email": email, "password": password})

        # Logout is a cookie-authenticated write, so it is CSRF-protected --
        # the header has to be echoed the way a browser would.
        response = client.post("/api/v1/auth/logout", headers=csrf_headers(client))
        assert response.status_code == 200, response.get_data(as_text=True)

        headers = set_cookie_headers(response)
        for name in COOKIES:
            assert name in headers, f"{name} was not cleared"
            header = headers[name]
            cleared = "Max-Age=0" in header or "Expires=Thu, 01 Jan 1970" in header
            assert cleared, f"{name} was not expired: {header}"
