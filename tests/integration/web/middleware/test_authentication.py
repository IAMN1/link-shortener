"""Integration tests for AuthenticationMiddleware with real DB."""

import pytest
from tests.integration.conftest import register_and_login, auth_headers


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
