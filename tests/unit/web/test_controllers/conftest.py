"""What the tests of the admin health endpoint share.

Two files ask the same endpoint the same way -- one checks that each
component is published under its own name, the other that every key of the
answer reaches the page -- and each had its own copy of the path, the
counter fixture, the controller lookup and the stubbing helper. The copies
carried the same eight distinct counter values for the same reason, which
is exactly the kind of agreement that stops being true silently.
"""

from dataclasses import replace

import pytest

from link_shortener.application.ports.logging_status import (
    ChainStatus, LoggingStatus,
)
from link_shortener.application.ports.health_check import HealthSnapshot
from link_shortener.application.use_cases.stats.get_service_health import (
    ServiceHealthStatus,
)


LOGGING = LoggingStatus(
    worker=4242,
    logger=ChainStatus(
        active="structlog",
        dropped_calls=11,
        failed_checks=12,
        lost_log_lines=13,
        last_check="healthy",
    ),
    audit=ChainStatus(
        active="standard_audit",
        dropped_calls=21,
        failed_checks=22,
        lost_log_lines=23,
        last_check="unhealthy",
    ),
    journals_written=("application", "error", "audit"),
    journals_unavailable=(),
)
"""Eight values, no two alike, beside the process that holds them.

A counter published under another's name then shows up as the wrong
number rather than as the same one -- three of the eight were zero once,
and a body publishing one chain's count under both names read as correct.
The worker id is unlike all eight for the same reason.

The two chains are given different findings for the same reason: one
verdict repeated is a body that can publish either chain's under both
headings and still read as correct.
"""


@pytest.fixture
def admin_controller(app):
    """
    The ``AdminApiController`` behind the registered routes.

    Args:
        app: The application under test.

    Returns:
        The controller instance, whose ``admin_service`` is a mock.
    """
    for view in app.view_functions.values():
        if (
            hasattr(view, "__self__")
            and view.__self__.__class__.__name__ == "AdminApiController"
        ):
            return view.__self__

    raise AssertionError("the admin controller is not registered")


@pytest.fixture
def logging_with_journals_missing():
    """
    The same chain state, with journals that could not be opened.

    Built by replacing one field of ``LOGGING`` rather than by naming ten
    of them again: the counters are distinct for a reason written above,
    and a second copy of them is a second thing to keep true.

    Returns:
        A callable taking ``JournalUnavailable`` entries and returning the
        status carrying them.
    """
    def carrying(*entries):
        return replace(LOGGING, journals_unavailable=entries)

    return carrying


@pytest.fixture
def health_of(admin_controller):
    """
    Make the health use case answer with a given state.

    Args:
        admin_controller: The controller whose service is stubbed.

    Returns:
        A callable taking overrides on ``ServiceHealthStatus``; everything
        not named is up.
    """
    def answering(**overrides):
        fields = {
            "database": True,
            # Two questions, like the cache pair below: "answered" and
            # "holds our tables". Both default to up, so a test naming
            # neither describes a working deployment.
            "database_schema": True,
            "redis": True,
            # A configured cache that answers, unless a test says
            # otherwise: the two are separate questions, and a default of
            # "no cache here" would make every other assertion in these
            # files about a deployment nobody runs.
            "cache_configured": True,
            "task_queue": True,
            "rate_limiter": True,
            "timed_out": (),
            "logging": LOGGING,
        }
        fields.update(overrides)
        # The verdict is derived from the same fields rather than typed
        # beside them. Written by hand here, this fixture would hold a
        # second account of what those booleans mean -- which is the
        # arrangement the snapshot was given `component_states` to end,
        # and a fixture stating it twice can agree with a page that
        # disagrees with the service.
        fields.setdefault("components", HealthSnapshot(
            database=fields["database"],
            database_schema=fields["database_schema"],
            cache=fields["redis"],
            cache_configured=fields["cache_configured"],
            task_queue=fields["task_queue"],
            task_queue_configured=fields.get("task_queue_configured", True),
            rate_limiter=fields["rate_limiter"],
            timed_out=tuple(fields["timed_out"]),
        ).component_states())
        status = ServiceHealthStatus(**fields)
        admin_controller.admin_service.get_service_health.return_value = status
        return status

    return answering
