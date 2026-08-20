"""Tests for the authentication controller."""
from unittest.mock import MagicMock

from link_shortener.application.dtos.auth import RefreshedTokens
from link_shortener.domain import DomainError, ValidationError
from link_shortener.web.middleware.csrf import (
    CSRF_COOKIE_NAME, CSRF_HEADER_NAME, build_csrf_token
)
from tests.unit.web.conftest import TEST_SECRET_KEY, TEST_USER_ID


def _get_auth_controller(app):
    """Extract the AuthController instance from the registered blueprints."""
    for view in app.view_functions.values():
        # auth_controller methods are bound to the AuthController instance
        if hasattr(view, '__self__') and view.__self__.__class__.__name__ == 'AuthController':
            return view.__self__
    return None


class TestAuthController:
    """Tests for AuthController endpoints."""

    def test_login_success(self, app, client):
        """POST /api/v1/auth/login returns 200 with tokens on valid credentials."""
        ctrl = _get_auth_controller(app)
        assert ctrl is not None, "AuthController not found"

        mock_result = MagicMock()
        mock_result.access_token = "access-token-123"
        mock_result.refresh_token = "refresh-token-456"
        mock_result.user.id = "user-1"
        mock_result.user.email = "test@example.com"
        mock_result.user.roles = ["user"]
        mock_result.user.is_active = True
        ctrl.auth_service.login.return_value = mock_result

        response = client.post(
            "/api/v1/auth/login",
            json={"email": "test@example.com", "password": "secret"},
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["access_token"] == "access-token-123"
        assert data["user"]["email"] == "test@example.com"

    def test_login_missing_fields(self, client):
        """POST /api/v1/auth/login returns 400 when email or password is missing."""
        response = client.post("/api/v1/auth/login", json={})
        assert response.status_code == 400

    def test_login_invalid_credentials(self, app, client):
        """POST /api/v1/auth/login returns 401 on bad credentials."""
        ctrl = _get_auth_controller(app)
        ctrl.auth_service.login.side_effect = DomainError(
            "Invalid email or password", code="INVALID_CREDENTIALS"
        )

        response = client.post(
            "/api/v1/auth/login",
            json={"email": "test@example.com", "password": "wrong"},
        )
        assert response.status_code == 401
        # The envelope every other refusal in the API answers in: `error`
        # is the machine-readable code, the sentence is in `message`.
        body = response.get_json()
        assert body["error"] == "INVALID_CREDENTIALS"
        assert body["message"] == "Invalid email or password"

    def test_login_does_not_leak_internal_error(self, app, client):
        """An unexpected failure must not send exception text to the client."""
        ctrl = _get_auth_controller(app)
        secret = "connection to postgres://user:pw@db:5432 refused"
        ctrl.auth_service.login.side_effect = RuntimeError(secret)

        response = client.post(
            "/api/v1/auth/login",
            json={"email": "test@example.com", "password": "secret"},
        )
        assert response.status_code == 500
        assert secret not in response.get_data(as_text=True)

    def test_register_success(self, app, client):
        """POST /api/v1/auth/register returns 202 and names no account.

        The use case is mocked, so it returns a ``MagicMock`` -- which has
        an attribute for every name asked of it. That is the point here:
        the controller must publish nothing from it, and a controller that
        went back to reading ``result.id`` would put the mock's stand-in
        for an identifier in the body and fail this.
        """
        response = client.post(
            "/api/v1/auth/register",
            json={"email": "new@example.com", "password": "secret123"},
        )
        assert response.status_code == 202
        data = response.get_json()
        assert set(data) == {"message"}
        assert "new@example.com" not in response.get_data(as_text=True)

    def test_register_missing_fields(self, client):
        """POST /api/v1/auth/register returns 400 when fields are missing."""
        response = client.post("/api/v1/auth/register", json={})
        assert response.status_code == 400

    def test_register_failure(self, app, client):
        """POST /api/v1/auth/register returns 400 on domain error.

        The refused thing is a property of what was sent -- here a
        password the policy will not take -- and not of who is registered,
        which is why this one is still answered out loud.
        """
        ctrl = _get_auth_controller(app)
        ctrl.auth_service.register.side_effect = ValidationError(
            "Password is too common", field="password"
        )

        response = client.post(
            "/api/v1/auth/register",
            json={"email": "weak@example.com", "password": "secret123"},
        )
        assert response.status_code == 400
        body = response.get_json()
        assert body["error"] == "VALIDATION_ERROR"
        assert body["message"] == "Password is too common"

    def test_register_does_not_leak_internal_error(self, app, client):
        """An unexpected failure must not send exception text to the client."""
        ctrl = _get_auth_controller(app)
        secret = "IntegrityError on table users at /srv/app/db.py:88"
        ctrl.auth_service.register.side_effect = RuntimeError(secret)

        response = client.post(
            "/api/v1/auth/register",
            json={"email": "boom@example.com", "password": "secret123"},
        )
        assert response.status_code == 500
        assert secret not in response.get_data(as_text=True)

    def test_register_does_not_leak_a_5xx_domain_sentence(self, app, client):
        """A DomainError worded for the log must not be read as a 400.

        Both auth routes answer a ``DomainError`` with a status of their
        own, which is what takes them past the handler -- and the handler
        is where the rule lived that a sentence behind a 5xx code is
        replaced by a generic one. So the rule had to be carried across:
        answered here as 400, ``CONFIGURATION_ERROR`` would have told an
        anonymous caller which part of the deployment is misconfigured.
        """
        ctrl = _get_auth_controller(app)
        secret = "Default role 'user' not found"
        ctrl.auth_service.register.side_effect = DomainError(
            secret, code="CONFIGURATION_ERROR"
        )

        response = client.post(
            "/api/v1/auth/register",
            json={"email": "misconfigured@example.com", "password": "secret123"},
        )

        assert response.status_code == 400
        assert secret not in response.get_data(as_text=True)
        assert response.get_json()["error"] == "CONFIGURATION_ERROR"

    def test_login_does_not_leak_a_5xx_domain_sentence(self, app, client):
        """The same rule on the route beside it, which answers 401."""
        ctrl = _get_auth_controller(app)
        secret = "Default role 'user' not found"
        ctrl.auth_service.login.side_effect = DomainError(
            secret, code="CONFIGURATION_ERROR"
        )

        response = client.post(
            "/api/v1/auth/login",
            json={"email": "test@example.com", "password": "secret"},
        )

        assert response.status_code == 401
        assert secret not in response.get_data(as_text=True)

    def test_a_registration_the_deployment_cannot_do_still_says_so(
        self, app, client
    ):
        """The one 5xx code whose sentence is written for the reader.

        ``REGISTRATION_UNAVAILABLE`` is answered 503 by the status table
        and 400 here, and either way its sentence is shown: a person who
        pressed Register is owed more than "an internal error occurred".
        It is a separate code from ``CONFIGURATION_ERROR`` above for
        exactly that reason -- one code cannot have two audiences.
        """
        ctrl = _get_auth_controller(app)
        ctrl.auth_service.register.side_effect = DomainError(
            "Registration is unavailable", code="REGISTRATION_UNAVAILABLE"
        )

        response = client.post(
            "/api/v1/auth/register",
            json={"email": "nobody@example.com", "password": "secret123"},
        )

        assert response.status_code == 400
        body = response.get_json()
        assert body["error"] == "REGISTRATION_UNAVAILABLE"
        assert body["message"] == "Registration is unavailable"

    def test_logout(self, client):
        """POST /api/v1/auth/logout returns 200 and clears cookies."""
        response = client.post("/api/v1/auth/logout")
        assert response.status_code == 200
        data = response.get_json()
        assert data["message"] == "Logged out"

    def test_refresh_no_token(self, client):
        """POST /api/v1/auth/refresh returns 401 when no refresh cookie is set."""
        response = client.post("/api/v1/auth/refresh")
        assert response.status_code == 401

    def test_refresh_success(self, app, client):
        """POST /api/v1/auth/refresh returns 200 with new access token."""
        ctrl = _get_auth_controller(app)
        ctrl.auth_service.refresh.return_value = RefreshedTokens(
            access_token="new-access-token", refresh_token="new-refresh-token"
        )

        client.set_cookie("refresh_token", "valid-refresh-token", path="/")
        csrf = build_csrf_token(TEST_SECRET_KEY, TEST_USER_ID)
        client.set_cookie(CSRF_COOKIE_NAME, csrf, path="/")
        response = client.post(
            "/api/v1/auth/refresh", headers={CSRF_HEADER_NAME: csrf}
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["access_token"] == "new-access-token"

    def test_refresh_renews_both_cookies(self, app, client):
        """Both tokens are rotated, so both cookies have to be replaced."""
        ctrl = _get_auth_controller(app)
        ctrl.auth_service.refresh.return_value = RefreshedTokens(
            access_token="new-access-token", refresh_token="new-refresh-token"
        )

        client.set_cookie("refresh_token", "valid-refresh-token", path="/")
        csrf = build_csrf_token(TEST_SECRET_KEY, TEST_USER_ID)
        client.set_cookie(CSRF_COOKIE_NAME, csrf, path="/")
        response = client.post(
            "/api/v1/auth/refresh", headers={CSRF_HEADER_NAME: csrf}
        )
        assert response.status_code == 200
        assert client.get_cookie("access_token").value == "new-access-token"
        # Leaving the spent token in place would make the next refresh look
        # like a replay and revoke the session.
        assert client.get_cookie("refresh_token").value == "new-refresh-token"

    def test_refresh_invalid_token(self, app, client):
        """POST /api/v1/auth/refresh returns 401 on invalid refresh token."""
        ctrl = _get_auth_controller(app)
        ctrl.auth_service.refresh.return_value = None

        client.set_cookie("refresh_token", "invalid-refresh-token", path="/")
        csrf = build_csrf_token(TEST_SECRET_KEY, TEST_USER_ID)
        client.set_cookie(CSRF_COOKIE_NAME, csrf, path="/")
        response = client.post(
            "/api/v1/auth/refresh", headers={CSRF_HEADER_NAME: csrf}
        )
        assert response.status_code == 401
