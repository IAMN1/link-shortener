"""
``GET /api/v1/admin/health`` names each component, and names it correctly.

The test that covered this endpoint set ``database``, ``cache``,
``task_queue`` and ``rate_limiter`` all to ``True``, so no assertion could
tell one field from another: reading ``health.database`` under the key
``cache`` produces exactly the answer such a test expects. Every such swap
in the body passes everything else, which is a Redis that has stopped
answering shown to an
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

The path, the counter values, the controller lookup and the stubbing
helper are in this directory's ``conftest.py``: the file next door checks
the same endpoint from the other side -- that every key of the answer
reaches the page -- and the two carried the same four copies.
"""

import pytest


COMPONENTS = [
    ("database", "database"),
    ("redis", "cache"),
    ("task_queue", "task_queue"),
    ("rate_limiter", "rate_limiter"),
]


class TestEachComponentIsReportedAsItself:

    @pytest.mark.parametrize("attribute, key", COMPONENTS)
    def test_the_one_that_is_down_is_the_one_reported_down(
        self, client, health_of, attribute, key
    ):
        """
        Args:
            attribute: Field of the status object that is down.
            key: Key it must be published under.
        """
        health_of(**{attribute: False})

        body = client.get("/api/v1/admin/health").get_json()

        assert body[key] is False
        assert [
            other for _, other in COMPONENTS
            if other != key and body[other] is not True
        ] == []

    def test_everything_up_is_reported_as_everything_up(
        self, client, health_of
    ):
        # The premise: without it the assertions above could be a body that
        # answers False to everything.
        health_of()

        body = client.get("/api/v1/admin/health").get_json()

        assert [key for _, key in COMPONENTS if body[key] is not True] == []


class TestEachCounterIsPublishedUnderItsOwnName:

    def test_the_logging_section_is_exactly_what_the_reader_holds(
        self, client, health_of
    ):
        # Compared whole rather than field by field: a body that adds a key,
        # drops one or reports a chain twice is as wrong as one that swaps
        # two numbers, and only equality of the section says all three.
        health_of()

        body = client.get("/api/v1/admin/health").get_json()

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
        self, client, health_of
    ):
        """The four are reported beside the chains, not instead of them."""
        health_of()

        body = client.get("/api/v1/admin/health").get_json()

        assert set(body) == {
            "database", "cache", "task_queue", "rate_limiter", "logging"
        }
