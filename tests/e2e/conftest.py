"""
Fixtures for E2E tests.

E2E tests verify complete user journeys through the full stack.
They use the real Flask test client with real in-memory SQLite
(level 1) for fast execution, or can be pointed at a running
Docker instance for true E2E (level 3).

Run level 1 (fast):
    uv run pytest tests/e2e/ -v

Run level 3 (Docker):
    docker compose -f docker-compose.test.yml up -d
    E2E_BASE_URL=http://localhost:5000 uv run pytest tests/e2e/ -v --base-url
"""

import pytest
import os


@pytest.fixture(scope="session")
def base_url():
    """Base URL for E2E tests. Set E2E_BASE_URL env var for real server."""
    return os.environ.get("E2E_BASE_URL", "")


@pytest.fixture(scope="session")
def app():
    """Flask app for E2E tests (level 1: in-memory)."""
    import sys
    sys.path.insert(0, "src")

    from link_shortener.infrastructure.configs.app.testing import TestingConfig

    class E2ETestConfig(TestingConfig):
        LOGGING_ENABLED = False
        AUDIT_ENABLED = False
        AUTO_SEED_ROLES = False
        RATE_LIMIT_AUTH_DISABLED = True

    from link_shortener.web.app_factory import create_app
    application = create_app(config=E2ETestConfig())

    with application.app_context():
        from link_shortener.infrastructure.database.seed import seed_base_roles
        db = application.container.get_db_manager()
        db.create_tables()
        with db.session() as session:
            seed_base_roles(session)

    yield application

    with application.app_context():
        application.container.close()


@pytest.fixture()
def client(app):
    return app.test_client()
