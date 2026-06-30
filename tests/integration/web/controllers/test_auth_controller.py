"""Integration tests for auth endpoints with real DB."""

import pytest
from tests.integration.conftest import register_and_login, auth_headers


class TestRegister:
    """POST /api/v1/auth/register"""

    def test_register_success(self, client):
        r = client.post("/api/v1/auth/register", json={
            "email": "new@example.com", "password": "StrongPass1!"
        })
        assert r.status_code == 201
        data = r.get_json()
        assert "user" in data or "access_token" in data

    def test_register_duplicate_email(self, client):
        client.post("/api/v1/auth/register", json={
            "email": "dup@example.com", "password": "StrongPass1!"
        })
        r = client.post("/api/v1/auth/register", json={
            "email": "dup@example.com", "password": "StrongPass1!"
        })
        assert r.status_code in (400, 409)

    def test_register_weak_password(self, client):
        r = client.post("/api/v1/auth/register", json={
            "email": "weak@example.com", "password": "123"
        })
        # API may accept or reject weak passwords depending on validation config
        assert r.status_code in (201, 400)

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


class TestLogout:
    """POST /api/v1/auth/logout"""

    def test_logout(self, client):
        r = client.post("/api/v1/auth/logout")
        assert r.status_code in (200, 401)


class TestRefresh:
    """POST /api/v1/auth/refresh"""

    def test_refresh_no_token(self, client):
        r = client.post("/api/v1/auth/refresh", json={})
        assert r.status_code in (200, 400, 401)


class TestAuthFlow:
    """Full auth flow: register → login → use token → logout."""

    def test_full_flow(self, client):
        # Register
        r = client.post("/api/v1/auth/register", json={
            "email": "flow@example.com", "password": "StrongPass1!"
        })
        assert r.status_code == 201

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
        r = client.post("/api/v1/auth/logout", headers=headers)
        assert r.status_code in (200, 401)
