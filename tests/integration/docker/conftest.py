"""
Fixtures for level 2 integration tests (real PostgreSQL + Redis).

Automatically starts Docker services before tests and stops after.
No manual docker compose commands needed.
"""

import os
import time
import subprocess
import pytest
import redis
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

POSTGRES_URL = "postgresql+psycopg://test_user:test_password@localhost:5433/test_shortener"
REDIS_URL = "redis://:test_redis_pass@localhost:6380/0"
COMPOSE_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "..", "docker-compose.test.yml")


def _run_compose(*args):
    """Run docker compose command."""
    cmd = ["docker", "compose", "-f", COMPOSE_FILE] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60)


def _wait_for_service(check_fn, name, max_retries=30, delay=1):
    """Wait for a service to become available."""
    for i in range(max_retries):
        try:
            if check_fn():
                return True
        except Exception:
            pass
        time.sleep(delay)
    return False


def _pg_check():
    engine = create_engine(POSTGRES_URL)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    engine.dispose()
    return True


def _redis_check():
    r = redis.from_url(REDIS_URL)
    r.ping()
    r.close()
    return True


@pytest.fixture(scope="session", autouse=True)
def docker_services():
    """Start Docker services before tests, stop after."""
    # Start services
    result = _run_compose("up", "-d")
    if result.returncode != 0:
        pytest.skip(f"Failed to start Docker services: {result.stderr}")

    # Wait for PostgreSQL
    if not _wait_for_service(_pg_check, "PostgreSQL"):
        _run_compose("down", "-v")
        pytest.skip("PostgreSQL did not become healthy in time")

    # Wait for Redis
    if not _wait_for_service(_redis_check, "Redis"):
        _run_compose("down", "-v")
        pytest.skip("Redis did not become healthy in time")

    yield

    # Cleanup: stop services
    _run_compose("down", "-v")


@pytest.fixture(scope="session")
def pg_engine():
    engine = create_engine(POSTGRES_URL, echo=False)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def pg_session_factory(pg_engine):
    return sessionmaker(bind=pg_engine)


@pytest.fixture(scope="session")
def redis_client():
    r = redis.from_url(REDIS_URL, decode_responses=True)
    yield r
    r.close()


@pytest.fixture(autouse=True)
def _clean_db(pg_engine):
    yield
    with pg_engine.connect() as conn:
        conn.execute(text("TRUNCATE urls, user_roles, role_permissions, "
                          "users, roles, permissions CASCADE"))
        conn.commit()


@pytest.fixture()
def db_session(pg_session_factory):
    session = pg_session_factory()
    yield session
    session.close()


@pytest.fixture(scope="session")
def app():
    """Flask app connected to real PostgreSQL + Redis."""
    from link_shortener.infrastructure.configs.app.testing import TestingConfig

    class DockerTestConfig(TestingConfig):
        DATABASE_URL = POSTGRES_URL
        DATABASE_TYPE = "postgresql"
        REDIS_ENABLED = True
        REDIS_URL = REDIS_URL
        CELERY_ENABLED = False
        CACHE_ENABLED = True
        LOGGING_ENABLED = False
        AUDIT_ENABLED = False
        AUTO_SEED_ROLES = False

    from link_shortener.web.app_factory import create_app
    application = create_app(config=DockerTestConfig())

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
    return app.test_client()
