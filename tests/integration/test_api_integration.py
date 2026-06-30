"""
Integration tests for API endpoints.

Tests validation, error handling, and endpoint routing
using the real Flask app with in-memory database.
"""

import pytest
from link_shortener.infrastructure.configs.app.testing import TestingConfig
from link_shortener.web.app_factory import create_app


class TestConfig(TestingConfig):
    TESTING = True
    DEBUG = False
    SECRET_KEY = "test-secret-key"
    SHORT_CODE_SECRET_PEPPER = "test-pepper"
    DATABASE_URL = "sqlite:///:memory:"
    REDIS_ENABLED = False
    CACHE_ENABLED = False
    LOGGING_ENABLED = False
    AUDIT_ENABLED = False
    AUTO_SEED_ROLES = False
    BASE_URL = "http://testserver/"
    HOST = "testserver"
    PORT = 80
    COOKIE_SECURE = False


@pytest.fixture(scope="module")
def app():
    app = create_app(config=TestConfig())
    app.config["TESTING"] = True
    # Create all tables for in-memory SQLite and seed roles
    with app.app_context():
        from link_shortener.infrastructure.database.models.base import Base
        from link_shortener.infrastructure.database.seed import seed_base_roles
        db_manager = app.container.get_db_manager()
        db_manager.create_tables()
        with db_manager.session() as session:
            seed_base_roles(session)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.get_json() == {"status": "healthy"}


class TestShortenValidation:
    def test_shorten_invalid_url_returns_400(self, client):
        response = client.post("/api/v1/shorten", json={"url": "not-a-url"})
        assert response.status_code == 400
        data = response.get_json()
        assert data["error"] == "VALIDATION_ERROR"

    def test_shorten_missing_url_returns_400(self, client):
        response = client.post("/api/v1/shorten", json={})
        assert response.status_code == 400
        data = response.get_json()
        assert data["error"] == "VALIDATION_ERROR"

    def test_shorten_empty_body_returns_400(self, client):
        response = client.post("/api/v1/shorten", json={})
        assert response.status_code == 400


class TestBatchValidation:
    def test_batch_missing_urls_returns_400(self, client):
        response = client.post("/api/v1/batch/shorten", json={})
        assert response.status_code == 400

    def test_batch_empty_list_returns_400(self, client):
        response = client.post("/api/v1/batch/shorten", json={"urls": []})
        assert response.status_code == 400


class TestLinkInfoNotFound:
    def test_get_nonexistent_link_returns_error(self, client):
        response = client.get("/api/v1/links/nonexist")
        assert response.status_code in (400, 404)


class TestAuthValidation:
    def test_login_missing_credentials_returns_400(self, client):
        response = client.post("/api/v1/auth/login", json={})
        assert response.status_code == 400

    def test_register_missing_credentials_returns_400(self, client):
        response = client.post("/api/v1/auth/register", json={})
        assert response.status_code == 400

    def test_login_wrong_password_returns_401(self, client):
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "nonexistent@test.com", "password": "wrong"},
        )
        assert response.status_code == 401


class TestAdminEndpointsUnauthorized:
    def test_admin_health_unauthorized(self, client):
        response = client.get("/api/v1/admin/health")
        # Should redirect to login or return 401/403
        assert response.status_code in (302, 401, 403)

    def test_admin_users_unauthorized(self, client):
        response = client.get("/api/v1/admin/users")
        assert response.status_code in (302, 401, 403)


class TestRedirectNotFound:
    def test_redirect_nonexistent_returns_error(self, client):
        response = client.get("/nonexistent123")
        assert response.status_code in (400, 404, 500)
