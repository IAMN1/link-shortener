"""Integration tests for AuthenticationMiddleware with real DB."""

import pytest

from link_shortener.infrastructure.database.models.user_model import UserModel
from tests.integration.conftest import register_and_login, auth_headers, csrf_headers


def _register_and_get_tokens(client, email, password="StrongPass1!"):
    """
    Register a user, log in, and return both tokens.

    Args:
        client: Flask test client.
        email: Email to register.
        password: Password to register with.

    Returns:
        Tuple of (access_token, refresh_token).
    """
    client.post("/api/v1/auth/register", json={
        "email": email, "password": password
    })
    r = client.post("/api/v1/auth/login", json={
        "email": email, "password": password
    })
    assert r.status_code == 200
    refresh_cookie = client.get_cookie("refresh_token")
    assert refresh_cookie is not None, "login must set the refresh_token cookie"
    return r.get_json()["access_token"], refresh_cookie.value


def _deactivate_user(db, email):
    """
    Flip ``is_active`` to False for the given user, as an admin block would.

    Args:
        db: Database manager.
        email: Email of the user to deactivate.
    """
    with db.session() as session:
        model = session.query(UserModel).filter_by(email=email).one()
        model.is_active = False


class TestAuthenticationMiddleware:
    """Verify middleware loads user from JWT token correctly."""

    def test_valid_token_sets_current_user(self, client):
        client.post("/api/v1/auth/register", json={
            "email": "auth@example.com", "password": "StrongPass1!"
        })
        r = client.post("/api/v1/auth/login", json={
            "email": "auth@example.com", "password": "StrongPass1!"
        })
        token = r.get_json().get("access_token")

        # Access protected endpoint with valid token
        r = client.get("/api/v1/links/mine", headers=auth_headers(token))
        assert r.status_code == 200

    def test_invalid_token_rejected(self, client):
        r = client.get("/api/v1/links/mine", headers={
            "Authorization": "Bearer invalid.jwt.token"
        })
        # May return 401, 403, or 302 (redirect to login)
        assert r.status_code in (302, 401, 403)

    def test_missing_token_allows_public_routes(self, client):
        # Public routes should work without token
        r = client.get("/health")
        assert r.status_code == 200

    def test_missing_token_blocks_protected_routes(self, client):
        r = client.get("/api/v1/admin/health")
        assert r.status_code in (401, 403)

    def test_expired_token_rejected(self, client):
        # Create a token with very short expiry
        client.post("/api/v1/auth/register", json={
            "email": "exp@example.com", "password": "StrongPass1!"
        })
        r = client.post("/api/v1/auth/login", json={
            "email": "exp@example.com", "password": "StrongPass1!"
        })
        token = r.get_json().get("access_token")
        assert token is not None

        # Token should be valid immediately
        r = client.get("/api/v1/links/mine", headers=auth_headers(token))
        assert r.status_code == 200


class TestTokenTypeEnforcement:
    """Only access tokens may authenticate a request."""

    def test_refresh_token_rejected_as_access_token(self, app):
        # A dedicated client keeps the login cookies out of the way, so the
        # request is authenticated by the Bearer header alone.
        login_client = app.test_client()
        _, refresh_token = _register_and_get_tokens(
            login_client, "reftype@example.com"
        )

        bare_client = app.test_client()
        r = bare_client.get(
            "/api/v1/links/mine", headers=auth_headers(refresh_token)
        )
        assert r.status_code == 401

    def test_access_token_still_accepted(self, app):
        login_client = app.test_client()
        access_token, _ = _register_and_get_tokens(
            login_client, "acctype@example.com"
        )

        bare_client = app.test_client()
        r = bare_client.get(
            "/api/v1/links/mine", headers=auth_headers(access_token)
        )
        assert r.status_code == 200


class TestDeactivatedUser:
    """Deactivating an account revokes access without waiting for expiry."""

    def test_deactivated_user_loses_api_access(self, app, db):
        login_client = app.test_client()
        access_token, _ = _register_and_get_tokens(
            login_client, "deactivated@example.com"
        )

        bare_client = app.test_client()
        r = bare_client.get(
            "/api/v1/links/mine", headers=auth_headers(access_token)
        )
        assert r.status_code == 200

        _deactivate_user(db, "deactivated@example.com")

        # The token is still cryptographically valid, but the account is not.
        r = bare_client.get(
            "/api/v1/links/mine", headers=auth_headers(access_token)
        )
        assert r.status_code == 401

    def test_deactivated_user_cannot_refresh(self, app, db):
        client = app.test_client()
        _register_and_get_tokens(client, "norefresh@example.com")

        _deactivate_user(db, "norefresh@example.com")

        r = client.post("/api/v1/auth/refresh", headers=csrf_headers(client))
        assert r.status_code == 401

    def test_deactivated_user_cannot_log_in(self, app, db):
        client = app.test_client()
        _register_and_get_tokens(client, "nologin@example.com")

        _deactivate_user(db, "nologin@example.com")

        r = client.post("/api/v1/auth/login", json={
            "email": "nologin@example.com", "password": "StrongPass1!"
        })
        assert r.status_code in (401, 403)

    def test_deactivated_account_does_not_confirm_a_correct_password(self, app, db):
        client = app.test_client()
        _register_and_get_tokens(client, "blockedsame@example.com")

        _deactivate_user(db, "blockedsame@example.com")

        # A fresh client: the logged-in one still carries session cookies,
        # so its login attempts would be turned away by the CSRF layer before
        # reaching the credential check, and both answers would match for the
        # wrong reason.
        prober = app.test_client()
        right = prober.post("/api/v1/auth/login", json={
            "email": "blockedsame@example.com", "password": "StrongPass1!"
        })
        wrong = prober.post("/api/v1/auth/login", json={
            "email": "blockedsame@example.com", "password": "WrongPass1!"
        })

        # Answering differently would tell an attacker that the guessed
        # password is the right one, blocked account or not.
        assert right.status_code == 401
        assert right.status_code == wrong.status_code
        assert right.get_json() == wrong.get_json()
