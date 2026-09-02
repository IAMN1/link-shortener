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

import importlib.util

from link_shortener.web.app_factory import create_app
from tests.integration.conftest import IntegrationTestConfig


if importlib.util.find_spec("schemathesis") is None:  # pragma: no cover
    collect_ignore_glob = ["*.py"]
"""Not collected at all when Schemathesis is not installed.

The tool lives in the ``contract`` dependency group so that it stays out
of the runtime image, and a plain ``uv sync`` -- which is what the quick
start tells a reader to run -- does not install a group. Left collectable,
the import in the test module ended the whole run before a single test of
the 4865 executed: ``ModuleNotFoundError: No module named 'schemathesis'``,
``Interrupted: 1 error during collection``. Measured on a fresh clone by
walking the quick start exactly as written.

A skip would have been the obvious answer and is wrong twice over:
``pytest.importorskip`` here runs after the test module has already been
imported, so it does not prevent the error, and this suite is run with
``--error-for-skips``, which is a rule worth keeping.

Silence is the cost, and the workflow pays it: CI installs the group and
runs ``tests/contract`` as a step of its own, where an empty collection is
exit code 5 -- so a run that lost this directory says so.
"""


class ContractConfig(IntegrationTestConfig):
    """What the contract run needs that a normal integration test does not.

    Derived rather than declared again. The settings that make a test
    build of this service -- sixteen of them: in-memory database, no
    Redis, no cache, no journals, no seeding, a fixed base URL -- were
    written out here a second time, and one added to the integration build
    would have appeared in one and not the other. That is not a cosmetic
    difference for this directory: the settings being repeated are the
    ones that keep a run from reaching real infrastructure, so the copy
    that fell behind would have been the one that quietly talked to it.

    What is genuinely its own is here and nothing else: a key of its own,
    and the two limits raised out of the way. Schemathesis generates
    hundreds of requests per operation, which would spend the guest
    allowance and trip the throttle before it had asked anything.
    """

    SECRET_KEY = "contract-secret-key-of-adequate-length"
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
