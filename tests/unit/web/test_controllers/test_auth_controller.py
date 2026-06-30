"""Tests for the authentication controller."""
from unittest.mock import MagicMock, Mock


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
        ctrl.login_use_case.execute.side_effect = Exception("Invalid credentials")

        response = client.post(
            "/api/v1/auth/login",
            json={"email": "test@example.com", "password": "wrong"},
        )
        assert response.status_code == 401

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
        ctrl.register_use_case.execute.side_effect = Exception("Email already exists")

        response = client.post(
            "/api/v1/auth/register",
            json={"email": "dup@example.com", "password": "secret123"},
        )
        assert response.status_code == 400

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
        ctrl.authentication_service.refresh_access_token.return_value = "new-access-token"

        client.set_cookie("refresh_token", "valid-refresh-token", path="/")
        response = client.post("/api/v1/auth/refresh")
        assert response.status_code == 200
        data = response.get_json()
        assert data["access_token"] == "new-access-token"

    def test_refresh_invalid_token(self, app, client):
        """POST /api/v1/auth/refresh returns 401 on invalid refresh token."""
        ctrl = _get_auth_controller(app)
        ctrl.authentication_service.refresh_access_token.return_value = None

        client.set_cookie("refresh_token", "invalid-refresh-token", path="/")
        response = client.post("/api/v1/auth/refresh")
        assert response.status_code == 401
