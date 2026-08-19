"""Everything ``/api/v1/admin/health`` answers reaches the health page.

The endpoint reports six things: the four components, and the two logging
chains with three counters each. The page rendered three of them --
``database``, ``cache``, ``task_queue`` -- and dropped the two that nothing
else in the service reports at all.

Which two, and why they are the ones worth having: the rate limiter fails
open. With its backend gone it stops enforcing and lets every request
through, brute-force protection on the sign-in endpoints included, and the
service goes on answering normally -- there is no error, no refusal and no
line in a log. The logging counters are the same shape one level down:
``FailoverService`` keeps them, and the controller's own comment says why
they are published -- "an audit trail that had stopped being written
looked, from every surface an operator has, exactly like one that was
fine".

This file is a guard rather than a rendering test: it reads the body the
endpoint actually produces and checks the page reads each key of it. A key
added to the body later and forgotten on the page fails here, which is the
failure that produced this file.
"""

from pathlib import Path

import pytest

from link_shortener.application.ports.logging_status import LoggingStatus
from link_shortener.application.use_cases.stats.get_service_health import (
    ServiceHealthStatus,
)


HEALTH_PATH = "/api/v1/admin/health"

SCRIPT = (
    Path(__file__).resolve().parents[4]
    / "src" / "link_shortener" / "web" / "static" / "js" / "pages" / "health.js"
)

TEMPLATE = (
    Path(__file__).resolve().parents[4]
    / "src" / "link_shortener" / "web" / "templates" / "dashboard" / "health.html"
)

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


@pytest.fixture
def body(app, client):
    """The body the endpoint answers with everything up."""
    admin_controller(app).admin_service.get_service_health.return_value = (
        ServiceHealthStatus(
            database=True, redis=True, task_queue=True,
            rate_limiter=True, logging=LOGGING,
        )
    )
    return client.get(HEALTH_PATH).get_json()


class TestNothingTheEndpointReportsIsDroppedOnTheWay:

    def test_the_page_reads_every_component_in_the_body(self, body):
        script = SCRIPT.read_text()

        missing = [
            key for key in body
            if key != "logging" and f"data.{key}" not in script
        ]

        assert missing == [], missing

    def test_the_page_reads_both_logging_chains(self, body):
        """
        The counters exist because a failover that swallowed the audit
        trail was invisible from every surface. A page that omits them
        leaves it invisible.
        """
        script = SCRIPT.read_text()

        assert "logging" in script
        for chain in body["logging"]:
            assert chain in script, chain

    def test_the_page_reads_every_counter_of_each_chain(self, body):
        script = SCRIPT.read_text()

        missing = [
            counter
            for chain in body["logging"].values()
            for counter in chain
            if counter not in script
        ]

        assert missing == [], missing

    def test_the_markup_has_somewhere_to_put_them(self):
        """
        A script writing into elements that do not exist writes nowhere,
        and does it silently: ``getElementById`` answers null and the
        page looks exactly as it did before.
        """
        markup = TEMPLATE.read_text()

        for anchor in ("health-limiter", "dot-limiter",
                       "logging-logger", "logging-audit"):
            assert anchor in markup, anchor
