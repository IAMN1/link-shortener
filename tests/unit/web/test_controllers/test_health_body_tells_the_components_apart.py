"""
``GET /api/v1/admin/health`` names each component, and names it correctly.

The test that covered this endpoint set ``database``, ``cache``,
``task_queue`` and ``rate_limiter`` all to ``True``, so no assertion could
tell one field from another: reading ``health.database`` under the key
``cache`` produced exactly the answer the test expected. Measured on the
mutation run of 2026-08-10 -- every such swap in the body survived the
whole suite, which is a Redis that has stopped answering shown to an
operator as healthy.

Distinguishable data is the whole fix. Each component is asked for on its
own, with that one down and the other three up, so a body reading the
wrong attribute reports a component that is up as down or the reverse.
The counters get pairwise distinct numbers for the same reason: three of
the eight were zero, and a body publishing one chain's count under both
names read as correct.

The status object is the real ``ServiceHealthStatus`` rather than a mock.
A mock answers any attribute, so a body reading a name this DTO does not
have -- ``health.cache``, say -- gets a ``MagicMock`` back instead of the
``AttributeError`` production would raise. What that costs is not a green
test but a misleading red one: ``jsonify`` cannot serialise the mock, so
the failure arrives as a 500 about serialisation rather than as an
assertion naming the field.
"""

import pytest

from link_shortener.application.ports.logging_status import LoggingStatus
from link_shortener.application.use_cases.stats.get_service_health import (
    ServiceHealthStatus,
)


HEALTH_PATH = "/api/v1/admin/health"

# The DTO attribute and the key it is published under. ``redis`` is the one
# pair whose two names differ, which is also the pair a swap hides in.
COMPONENTS = [
    ("database", "database"),
    ("redis", "cache"),
    ("task_queue", "task_queue"),
    ("rate_limiter", "rate_limiter"),
]

# Eight values, no two alike: any counter published under another's name
# shows up as the wrong number rather than as the same one.
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


def admin_controller(app):
    """
    Find the ``AdminApiController`` behind the registered routes.

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


def health_of(app, **overrides):
    """
    Make the health use case answer a given state.

    Args:
        app: The application under test.
        **overrides: Fields to set on ``ServiceHealthStatus``; everything
            not named is up.

    Returns:
        The status object the endpoint will report.
    """
    fields = {
        "database": True,
        "redis": True,
        "task_queue": True,
        "rate_limiter": True,
        "logging": LOGGING,
    }
    fields.update(overrides)
    status = ServiceHealthStatus(**fields)
    admin_controller(app).admin_service.get_service_health.return_value = status
    return status


class TestEachComponentIsReportedAsItself:

    @pytest.mark.parametrize("attribute, key", COMPONENTS)
    def test_the_one_that_is_down_is_the_one_reported_down(
        self, app, client, attribute, key
    ):
        """
        Args:
            attribute: Field of the status object that is down.
            key: Key it must be published under.
        """
        health_of(app, **{attribute: False})

        body = client.get(HEALTH_PATH).get_json()

        assert body[key] is False
        assert [
            other for _, other in COMPONENTS
            if other != key and body[other] is not True
        ] == []

    def test_everything_up_is_reported_as_everything_up(self, app, client):
        # The premise: without it the assertions above could be a body that
        # answers False to everything.
        health_of(app)

        body = client.get(HEALTH_PATH).get_json()

        assert [key for _, key in COMPONENTS if body[key] is not True] == []


class TestEachCounterIsPublishedUnderItsOwnName:

    def test_the_logging_section_is_exactly_what_the_reader_holds(
        self, app, client
    ):
        # Compared whole rather than field by field: a body that adds a key,
        # drops one or reports a chain twice is as wrong as one that swaps
        # two numbers, and only equality of the section says all three.
        health_of(app)

        body = client.get(HEALTH_PATH).get_json()

        assert body["logging"] == {
            "logger": {
                "active": "structlog",
                "dropped_calls": 11,
                "failed_checks": 12,
                "lost_log_lines": 13,
            },
            "audit": {
                "active": "standard_audit",
                "dropped_calls": 21,
                "failed_checks": 22,
                "lost_log_lines": 23,
            },
        }

    def test_the_components_are_not_swallowed_by_the_logging_section(
        self, app, client
    ):
        """The four are reported beside the chains, not instead of them."""
        health_of(app)

        body = client.get(HEALTH_PATH).get_json()

        assert set(body) == {
            "database", "cache", "task_queue", "rate_limiter", "logging"
        }
