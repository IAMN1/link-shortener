"""
Shared fixtures for integration tests.

All integration tests use a real in-memory SQLite database.
Fixtures provide app, client, db_manager, and authenticated helpers.
"""

import pytest
from link_shortener.infrastructure.configs.app.testing import TestingConfig
from link_shortener.web.app_factory import create_app
from link_shortener.web.middleware.csrf import (
    CSRF_COOKIE_NAME, CSRF_HEADER_NAME, build_csrf_token
)


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


def arm_csrf(client, user_id):
    """
    Helper: give a bare client a CSRF token valid for a specific user.

    Used to drive a request that did not come from a login, such as replaying
    a stolen refresh token. Building the token rather than reusing a captured
    one keeps the test aimed at the behaviour under test instead of failing
    on the CSRF check.

    Args:
        client: Flask test client to arm.
        user_id: User the token should be bound to.

    Returns:
        Header dict containing ``X-CSRF-Token``.
    """
    token = build_csrf_token(IntegrationTestConfig.SECRET_KEY, user_id)
    client.set_cookie(CSRF_COOKIE_NAME, token, path="/")
    return {CSRF_HEADER_NAME: token}


def csrf_headers(client, extra=None):
    """
    Helper: build headers echoing the client's CSRF cookie, as a browser does.

    Args:
        client: Flask test client holding the session cookies.
        extra: Additional headers to merge in.

    Returns:
        Header dict including ``X-CSRF-Token`` when the cookie is present.
    """
    headers = dict(extra or {})
    cookie = client.get_cookie(CSRF_COOKIE_NAME)
    if cookie:
        headers[CSRF_HEADER_NAME] = cookie.value
    return headers


def ensure_user(session, user_id):
    """
    Insert a bare ``users`` row so a link may legally point at it.

    SQLite enforces foreign keys now, as PostgreSQL always has, so a test
    that files a link under an invented owner is writing a row production
    could not hold. Creating the account is what the test meant; leaving it
    out only worked because the constraint was asleep.

    Args:
        session: Active SQLAlchemy session.
        user_id: Identifier the link will name as its owner.
    """
    from link_shortener.infrastructure.database.models.user_model import (
        UserModel
    )

    if session.get(UserModel, user_id) is not None:
        return

    session.add(
        UserModel(
            id=user_id,
            email=f"{user_id}@fixture.invalid",
            password_hash="not-a-real-hash",
        )
    )
    session.flush()
