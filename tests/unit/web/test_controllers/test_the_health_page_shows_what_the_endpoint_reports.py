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
endpoint actually produces and checks the page reads each thing in it. A
component added to the body later and forgotten on the page fails here,
which is the failure that produced this file.
"""

from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[4]
    / "src" / "link_shortener" / "web" / "static" / "js" / "pages" / "health.js"
)

TEMPLATE = (
    Path(__file__).resolve().parents[4]
    / "src" / "link_shortener" / "web" / "templates" / "dashboard" / "health.html"
)

def CHAINS(body):
    """
    The two logging chains of a health body, without what surrounds them.

    ``logging`` carries the worker id beside them, and it is neither a
    chain nor a counter: iterating the section whole walked into an
    integer and asked what its keys were.

    Args:
        body: The answer the endpoint gave.

    Returns:
        The ``logger`` and ``audit`` sections, by name.
    """
    return {
        name: section for name, section in body["logging"].items()
        if isinstance(section, dict)
    }


@pytest.fixture
def body(client, health_of):
    """The body the endpoint answers with everything up."""
    health_of()
    return client.get("/api/v1/admin/health").get_json()


class TestNothingTheEndpointReportsIsDroppedOnTheWay:

    def test_the_page_reads_every_component_the_body_judges(self, body):
        """
        Every dependency the endpoint reports has a row on the page.

        Asked of ``components`` rather than of the booleans beside it,
        because that is what the page draws now: the verdict is the
        snapshot's, and working it out again in JavaScript was how this
        page came to call a queue that does not exist "ok". The booleans
        are the measurement behind the same components -- one per row,
        under the same names -- so nothing they carry is dropped by
        reading the verdict instead.
        """
        script = SCRIPT.read_text()

        missing = [
            name for name in body["components"]
            if f"verdicts.{name}" not in script
        ]

        assert missing == [], missing
        assert "data.components" in script

    def test_the_measured_booleans_and_the_verdict_name_the_same_things(
        self, body
    ):
        """
        And the half that keeps the check above from narrowing.

        A component added to the body and left out of ``components``
        would be reported by the endpoint, judged by nobody and drawn
        nowhere -- and the check above would not see it, because it walks
        the verdict.
        """
        measured = {
            key for key in body
            if key not in {"logging", "components", "timed_out"}
            and not key.endswith("_configured")
            and not key.endswith("_schema")
        }

        assert measured == set(body["components"]), measured

    def test_the_page_reads_both_logging_chains(self, body):
        """
        The counters exist because a failover that swallowed the audit
        trail was invisible from every surface. A page that omits them
        leaves it invisible.
        """
        script = SCRIPT.read_text()

        assert "logging" in script
        for chain in CHAINS(body):
            assert chain in script, chain

    def test_the_page_reads_every_counter_of_each_chain(self, body):
        script = SCRIPT.read_text()

        missing = [
            counter
            for chain in CHAINS(body).values()
            for counter in chain
            if counter not in script
        ]

        assert missing == [], missing

    def test_the_page_says_whose_counters_these_are(self, body):
        """
        They are one worker process's, and a deployment runs several.

        The same service in the same state answered ``dropped_calls`` 16,
        27, 28 and 6 across twelve requests, by which worker took each
        one. Unlabelled on the page, the number reads as the service's --
        and a worker that served no traffic during an outage answers
        zero, which is the "everything is fine" this block exists to end.
        """
        script = SCRIPT.read_text()

        assert "logging.worker" in script

    def test_the_markup_has_somewhere_to_put_them(self):
        """
        A script writing into elements that do not exist writes nowhere,
        and does it silently: ``getElementById`` answers null and the
        page looks exactly as it did before.
        """
        markup = TEMPLATE.read_text()

        for anchor in ("health-limiter", "dot-limiter", "logging-worker",
                       "logging-logger", "logging-audit"):
            assert anchor in markup, anchor
