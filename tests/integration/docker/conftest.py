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


def _docker_is_available() -> bool:
    """
    Tell whether a Docker daemon can be reached at all.

    Separates "this machine cannot run these tests" from "these tests could
    not start". Only the first is a reason to skip; the second is a
    failure, and reporting it as a skip once turned a broken stack into a
    green run -- ``492 passed, 16 skipped`` where the suite had been
    printing ``508 passed``, with nothing but the arithmetic to notice.

    Returns:
        ``True`` when a daemon answers.
    """
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, text=True, timeout=20
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _diagnostics() -> str:
    """
    Collect what the stack has to say about why it did not come up.

    Returns:
        Container states and recent log lines, or a note on why not.
    """
    parts = []
    for label, args in (
        ("state", ("ps", "-a")),
        ("logs", ("logs", "--no-color", "--tail", "40")),
    ):
        try:
            result = _run_compose(*args)
            parts.append(f"--- {label} ---\n{result.stdout or result.stderr}")
        except subprocess.SubprocessError as error:
            parts.append(f"--- {label} unavailable: {error} ---")
    return "\n".join(parts)


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
    """
    Start the test stack before the tests and stop it after.

    A missing Docker daemon is the one condition worth skipping for: the
    machine cannot run these tests, and saying so is honest. Everything
    after that point is a failure. The distinction matters because it was
    absent: a port collision stopped the stack from starting, every skip
    branch below reported it as "skipped", and the run came back green
    while sixteen tests of real PostgreSQL and Redis behaviour had not
    executed.
    """
    if not _docker_is_available():
        pytest.skip(
            "Docker daemon is not reachable -- these tests require real "
            "PostgreSQL and Redis"
        )

    try:
        result = _run_compose("up", "-d")
    except subprocess.SubprocessError as error:
        pytest.fail(f"Docker is running but `compose up` did not finish: {error}")

    if result.returncode != 0:
        pytest.fail(
            "Docker is running but the test stack failed to start.\n"
            f"{result.stderr or result.stdout}\n{_diagnostics()}"
        )

    for check, name in ((_pg_check, "PostgreSQL"), (_redis_check, "Redis")):
        if _wait_for_service(check, name):
            continue
        diagnostics = _diagnostics()
        _run_compose("down", "-v")
        pytest.fail(
            f"{name} did not become reachable within the timeout, although "
            f"Docker is running.\n{diagnostics}"
        )

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
