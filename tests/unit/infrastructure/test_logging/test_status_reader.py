"""
The reader that puts the chain counters on the health endpoint.

``ComponentLoggingStatus`` is the only thing between the two managers and
the ``logging`` section of ``GET /api/v1/admin/health``, and nothing tested
it: the controller test builds ``LoggingStatus`` by hand, so a reader that
swapped the logger's counters for the audit's, or reported one chain twice,
would have gone through green. Measured: swapping the two triples in
``read()`` left the whole suite passing.
"""

import pytest

from link_shortener.infrastructure.logging.status_reader import (
    ComponentLoggingStatus,
)


class FakeManager:
    """A manager that answers the two questions the reader asks."""

    def __init__(self, name, counters):
        """
        Args:
            name: Active implementation to report.
            counters: ``(dropped, failed, lost)`` for this chain.
        """
        self._name = name
        self._counters = counters

    def counters(self):
        """Return this chain's three counters."""
        return self._counters

    def get_active_logger_name(self):
        """Answer as ``LoggerManager`` does."""
        return self._name

    def active_name(self):
        """Answer as ``AuditManager`` does."""
        return self._name


class FakeComponent:
    """A DI component holding a manager, or not holding one yet."""

    def __init__(self, manager=None):
        """
        Args:
            manager: The manager this component has built, if any.
        """
        self._manager = manager


class TestEachChainIsReportedAsItself:

    @pytest.fixture
    def status(self):
        """Two chains whose every number differs from the other's."""
        return ComponentLoggingStatus(
            FakeComponent(FakeManager("structlog", (1, 2, 3))),
            FakeComponent(FakeManager("structlog_audit", (4, 5, 6))),
        ).read()

    def test_the_logger_counters_are_the_logger_manager_s(self, status):
        assert status.logger_active == "structlog"
        assert (
            status.logger_dropped_calls,
            status.logger_failed_checks,
            status.logger_lost_log_lines,
        ) == (1, 2, 3)

    def test_the_audit_counters_are_the_audit_manager_s(self, status):
        """Every number distinct from the logger's, so a reader reporting
        one chain under both names cannot come out looking right."""
        assert status.audit_active == "structlog_audit"
        assert (
            status.audit_dropped_calls,
            status.audit_failed_checks,
            status.audit_lost_log_lines,
        ) == (4, 5, 6)


class TestAChainNobodyHasAskedFor:
    """Zeroes need the name beside them to be read correctly.

    A manager is built on the first logger anyone asks for, so a component
    that has not been used has nothing to report -- and asking here must not
    be what brings the chain into existence.
    """

    def test_a_component_without_a_manager_reports_not_started(self):
        """Read against the literal, not against ``NOT_STARTED`` itself.

        Comparing the answer with the constant it was built from moves both
        sides together: measured, ``NOT_STARTED = "structlog"`` -- a chain
        nobody has built reporting itself as a working one -- leaves such an
        assertion green, and the zeroes beside it then read as "nothing was
        lost" rather than as "nobody looked".
        """
        status = ComponentLoggingStatus(
            FakeComponent(), FakeComponent()
        ).read()

        assert status.logger_active == "not started"
        assert status.audit_active == "not started"
        assert status.logger_lost_log_lines == 0
        assert status.audit_lost_log_lines == 0

    def test_one_chain_started_does_not_start_the_other(self):
        component = FakeComponent()
        status = ComponentLoggingStatus(
            FakeComponent(FakeManager("standard", (7, 8, 9))), component
        ).read()

        assert status.logger_active == "standard"
        assert status.audit_active == ComponentLoggingStatus.NOT_STARTED
        assert component._manager is None
