"""
Fixtures for level 2 integration tests (real PostgreSQL + Redis).

Automatically starts Docker services before tests and stops after.
No manual docker compose commands needed.

Starting the stack, waiting for it and reporting a failure to start live in
``tests/support/real_stack``: ``tests/e2e`` walks the same containers, and
two copies of that logic would drift.
"""

import pytest
import redis
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from tests.support.real_stack import POSTGRES_URL, REDIS_URL


@pytest.fixture(scope="session", autouse=True)
def docker_services(real_stack):
    """Require the shared stack for every test in this directory.

    The containers themselves are started once per session by the
    ``real_stack`` fixture in ``tests/conftest.py`` -- ``tests/e2e`` runs
    against the same ones, and two fixtures taking them down independently
    is how one directory pulled the stack out from under the other.
    """
    yield


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
