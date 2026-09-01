"""
A stack of its own for the contract run.

Schemathesis generates hundreds of requests per operation and keeps what it
made: run against the shared session fixture it would spend the guest
allowance, trip the throttle and leave rows the other tests count. So this
directory builds its own application, with the two limits raised out of the
way and its own in-memory database.

The limits are raised rather than removed: a run that could not be
throttled would also not notice a throttle that stopped working, and
``tests/integration/web/middleware`` is where that is held.
"""

import pytest

from link_shortener.infrastructure.configs.app.testing import TestingConfig
from link_shortener.web.app_factory import create_app


class ContractConfig(TestingConfig):
    """What the contract run needs that a normal test does not."""

    TESTING = True
    DEBUG = False
    SECRET_KEY = "contract-secret-key-of-adequate-length"
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
    DEFAULT_RATE_LIMIT = 1_000_000
    GUEST_LINK_LIMIT = 1_000_000


def build_application():
    """The application the generated requests are sent to."""
    application = create_app(config=ContractConfig())
    application.config["TESTING"] = True

    with application.app_context():
        db_manager = application.container.get_db_manager()
        db_manager.create_tables()
        from link_shortener.infrastructure.database.seed import seed_base_roles

        with db_manager.session() as session:
            seed_base_roles(session)

    return application


@pytest.fixture(scope="session")
def contract_app():
    """The same application the module-level schema was loaded from."""
    from tests.contract.test_the_service_answers_its_own_document import APP

    return APP
