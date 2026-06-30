"""
Shared fixtures for integration tests.

All integration tests use a real in-memory SQLite database.
Fixtures provide app, client, db_manager, and authenticated helpers.
"""

import pytest
from link_shortener.infrastructure.configs.app.testing import TestingConfig
from link_shortener.web.app_factory import create_app


class IntegrationTestConfig(TestingConfig):
    """Config for integration tests: real DB, no external services."""
    TESTING = True
    DEBUG = False
    SECRET_KEY = "integration-test-secret"
    SHORT_CODE_SECRET_PEPPER = "integration-test-pepper"
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
    RATE_LIMIT_AUTH_DISABLED = True


@pytest.fixture(scope="session")
def app():
    """Create Flask app once per test session with real in-memory DB."""
    application = create_app(config=IntegrationTestConfig())
    application.config["TESTING"] = True

    with application.app_context():
        db_manager = application.container.get_db_manager()
        db_manager.create_tables()
        from link_shortener.infrastructure.database.seed import seed_base_roles
        with db_manager.session() as session:
            seed_base_roles(session)

    yield application

    with application.app_context():
        application.container.close()


@pytest.fixture()
def client(app):
    """Fresh test client per test."""
    return app.test_client()


@pytest.fixture()
def db(app):
    """Database manager for direct DB operations."""
    with app.app_context():
        yield app.container.get_db_manager()


@pytest.fixture()
def app_context(app):
    """Flask app context for tests that need it."""
    with app.app_context():
        yield app


def register_and_login(client, email="test@example.com", password="Test1234!"):
    """Helper: register a user and return access token."""
    client.post("/api/v1/auth/register", json={
        "email": email, "password": password
    })
    r = client.post("/api/v1/auth/login", json={
        "email": email, "password": password
    })
    data = r.get_json()
    return data.get("access_token")


def auth_headers(token):
    """Helper: build Authorization headers from token."""
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}
