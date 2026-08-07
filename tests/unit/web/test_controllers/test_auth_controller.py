"""Tests for the authentication controller."""
from unittest.mock import MagicMock, Mock

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
        ctrl.login_use_case.execute.return_value = mock_result

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
        ctrl.login_use_case.execute.side_effect = DomainError(
            "Invalid email or password", code="INVALID_CREDENTIALS"
        )

        response = client.post(
            "/api/v1/auth/login",
            json={"email": "test@example.com", "password": "wrong"},
        )
        assert response.status_code == 401
        assert response.get_json()["error"] == "Invalid email or password"

    def test_login_does_not_leak_internal_error(self, app, client):
        """An unexpected failure must not send exception text to the client."""
        ctrl = _get_auth_controller(app)
        secret = "connection to postgres://user:pw@db:5432 refused"
        ctrl.login_use_case.execute.side_effect = RuntimeError(secret)

        response = client.post(
            "/api/v1/auth/login",
            json={"email": "test@example.com", "password": "secret"},
        )
        assert response.status_code == 500
        assert secret not in response.get_data(as_text=True)

    def test_register_success(self, app, client):
        """POST /api/v1/auth/register returns 201 on success."""
        ctrl = _get_auth_controller(app)
        mock_result = MagicMock()
        mock_result.id = "user-1"
        mock_result.email = "new@example.com"
        mock_result.roles = ["user"]
        mock_result.is_active = True
        ctrl.register_use_case.execute.return_value = mock_result

        response = client.post(
            "/api/v1/auth/register",
            json={"email": "new@example.com", "password": "secret123"},
        )
        assert response.status_code == 201
        data = response.get_json()
        assert data["user"]["email"] == "new@example.com"

    def test_register_missing_fields(self, client):
        """POST /api/v1/auth/register returns 400 when fields are missing."""
        response = client.post("/api/v1/auth/register", json={})
        assert response.status_code == 400

    def test_register_failure(self, app, client):
        """POST /api/v1/auth/register returns 400 on domain error."""
        ctrl = _get_auth_controller(app)
        ctrl.register_use_case.execute.side_effect = ValidationError(
            "Email already registered", field="email"
        )

        response = client.post(
            "/api/v1/auth/register",
            json={"email": "dup@example.com", "password": "secret123"},
        )
        assert response.status_code == 400
        assert response.get_json()["error"] == "Email already registered"

    def test_register_does_not_leak_internal_error(self, app, client):
        """An unexpected failure must not send exception text to the client."""
        ctrl = _get_auth_controller(app)
        secret = "IntegrityError on table users at /srv/app/db.py:88"
        ctrl.register_use_case.execute.side_effect = RuntimeError(secret)

        response = client.post(
            "/api/v1/auth/register",
            json={"email": "boom@example.com", "password": "secret123"},
        )
        assert response.status_code == 500
        assert secret not in response.get_data(as_text=True)

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
        ctrl.authentication_service.refresh_access_token.return_value = RefreshedTokens(
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
        ctrl.authentication_service.refresh_access_token.return_value = RefreshedTokens(
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
        ctrl.authentication_service.refresh_access_token.return_value = None

        client.set_cookie("refresh_token", "invalid-refresh-token", path="/")
        csrf = build_csrf_token(TEST_SECRET_KEY, TEST_USER_ID)
        client.set_cookie(CSRF_COOKIE_NAME, csrf, path="/")
        response = client.post(
            "/api/v1/auth/refresh", headers={CSRF_HEADER_NAME: csrf}
        )
        assert response.status_code == 401
