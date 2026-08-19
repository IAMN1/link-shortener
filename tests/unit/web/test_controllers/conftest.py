"""What the tests of the admin health endpoint share.

Two files ask the same endpoint the same way -- one checks that each
component is published under its own name, the other that every key of the
answer reaches the page -- and each had its own copy of the path, the
counter fixture, the controller lookup and the stubbing helper. The copies
carried the same eight distinct counter values for the same reason, which
is exactly the kind of agreement that stops being true silently.
"""

import pytest

from link_shortener.application.ports.logging_status import LoggingStatus
from link_shortener.application.use_cases.stats.get_service_health import (
    ServiceHealthStatus,
)


HEALTH_PATH = "/api/v1/admin/health"

LOGGING = LoggingStatus(
    logger_active="structlog",
    logger_dropped_calls=11,
    logger_failed_checks=12,
    logger_lost_log_lines=13,
    audit_active="standard_audit",
    audit_dropped_calls=21,
    audit_failed_checks=22,
    audit_lost_log_lines=23,
)
"""Eight values, no two alike.

A counter published under another's name then shows up as the wrong
number rather than as the same one -- three of the eight were zero once,
and a body publishing one chain's count under both names read as correct.
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
            "redis": True,
            "task_queue": True,
            "rate_limiter": True,
            "logging": LOGGING,
        }
        fields.update(overrides)
        status = ServiceHealthStatus(**fields)
        admin_controller.admin_service.get_service_health.return_value = status
        return status

    return answering
