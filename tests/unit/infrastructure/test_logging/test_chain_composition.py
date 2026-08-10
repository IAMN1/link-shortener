"""
Which implementations each configured mode actually builds.

Nothing held the audit half before. Every test configuration switches
logging and auditing off, so the branch that turns a mode into a list of
implementations was reached by almost nothing. Measured against the whole
suite with this file removed (1665 tests):

* ``AuditManager``'s ``auto`` branch building nothing -- no auditing at
  all, in the default production mode -- leaves the suite green;
* its ``null`` branch returning the real implementations -- a full audit
  trail where an operator had switched it off -- does the same;
* the same two mutations on ``LoggerManager`` are *not* free: ``auto``
  returning ``["null"]`` fails
  ``test_logging_health.py::TestHealthOnTheRealWiring::test_a_check_leaves_the_work_where_the_operator_put_it[auto]``,
  and ``null`` returning the real implementations fails
  ``test_module_logger.py::TestItIsWhatOneImplementationGetsYou::test_the_manager_hands_it_out_when_there_is_no_failover``,
  which asserts ``_failover_service is None`` before it asks what the
  logger is.

A third mutation, ``if len(loggers) == 1`` widened to ``>= 1``, so that
failover is never built at all, is *not* in that list: it is caught
already, by two tests in
``tests/integration/infrastructure/test_logging_health.py``. Said here
because a file that claims more than it holds is the thing this one is
against.

The order of preference is asserted as well, not only the membership: it
is the difference between structlog and standard answering first, and a
silent swap of the two is exactly the shape of change this file exists to
make loud.
"""

import pytest

from link_shortener.infrastructure.logging.managers.audit_manager import (
    AuditManager,
)
from link_shortener.infrastructure.logging.managers.logger_manager import (
    LoggerManager,
)


def chain_of(manager) -> list:
    """
    Name every implementation the manager put in its chain, in order.

    Args:
        manager: A ``LoggerManager`` or ``AuditManager``.

    Returns:
        Names from the failover service, or a single name when the manager
        built no failover at all.
    """
    service = manager._failover_service
    if service is None:
        return ["<no failover>"]

    return [name for _, name in service._services]


class TestTheLoggerChain:

    @pytest.mark.parametrize(
        "mode, expected",
        [
            ("auto", ["structlog", "standard"]),
            ("structlog", ["structlog", "standard"]),
            ("standard", ["standard", "structlog"]),
        ],
    )
    def test_a_mode_builds_the_pair_it_promises(self, mode, expected):
        assert chain_of(LoggerManager(logger_type=mode)) == expected

    def test_null_builds_one_implementation_and_no_failover(self):
        """One implementation is not a chain, and must not become one."""
        manager = LoggerManager(logger_type="null")

        assert manager._failover_service is None
        assert type(manager._active_logger).__name__ == "NullLogger"

    def test_an_unknown_mode_falls_back_to_the_default_pair(self):
        """Unrecognised is not the same as off.

        A typo must not silently disable logging; it gets what ``auto``
        gets, which is what this branch always did.
        """
        assert chain_of(LoggerManager(logger_type="nonsense")) == [
            "structlog", "standard"
        ]


class TestTheAuditChain:

    @pytest.mark.parametrize(
        "mode, expected",
        [
            ("auto", ["structlog_audit", "standard_audit"]),
            ("structlog", ["structlog_audit", "standard_audit"]),
            ("standard", ["standard_audit", "structlog_audit"]),
        ],
    )
    def test_a_mode_builds_the_pair_it_promises(self, mode, expected):
        assert chain_of(AuditManager(audit_type=mode)) == expected

    def test_null_writes_nothing_and_builds_no_failover(self):
        manager = AuditManager(audit_type="null")

        assert manager._failover_service is None
        assert type(manager._active_audit_logger).__name__ == "NullAuditLogger"


class TestOffMeansOffWhateverTheSpelling:
    """The case that turned a switch-off into a full audit trail."""

    @pytest.mark.parametrize("spelling", ["NULL", "Null", " null ", "nUlL"])
    def test_null_is_recognised_however_it_is_written(self, spelling):
        """Exact-string comparison sent all of these to the default.

        The default is the full chain, so an operator who wrote
        ``AUDIT_TYPE=NULL`` to switch auditing off got original_url,
        remote_addr and user_id written down instead.
        """
        manager = AuditManager(audit_type=spelling)

        assert manager._failover_service is None
        assert type(manager._active_audit_logger).__name__ == "NullAuditLogger"

    @pytest.mark.parametrize("spelling", ["STANDARD", " standard"])
    def test_the_order_modes_are_recognised_too(self, spelling):
        """``STANDARD`` used to leave the order it was asking to reverse."""
        assert chain_of(LoggerManager(logger_type=spelling)) == [
            "standard", "structlog"
        ]


class TestTheCountersComeFromTheChain:
    """``counters()`` can be made to answer zero, and nothing noticed.

    Measured: replacing both bodies with ``return 0, 0, 0`` left the whole
    suite green -- on the numbers introduced precisely so that "records
    are being lost" stops looking like "everything is fine". The reason is
    that every other test reads them off a ``FailoverService`` built by
    hand; nothing read them through a manager.
    """

    def test_a_manager_reports_what_its_failover_service_holds(self):
        manager = LoggerManager(logger_type="auto")
        service = manager._failover_service
        assert service is not None

        service._dropped_calls = 7
        service._failed_checks = 3
        service._lost_log_lines = 5

        assert manager.counters() == (7, 3, 5)

    def test_an_audit_manager_does_the_same(self):
        manager = AuditManager(audit_type="auto")
        service = manager._failover_service
        assert service is not None

        service._dropped_calls = 4
        service._failed_checks = 1
        service._lost_log_lines = 2

        assert manager.counters() == (4, 1, 2)

    @pytest.mark.parametrize("mode", ["null"])
    def test_without_failover_there_is_nothing_to_count(self, mode):
        """One implementation cannot fail over, and a call it refuses
        raises at the caller rather than being dropped here."""
        assert LoggerManager(logger_type=mode).counters() == (0, 0, 0)
        assert AuditManager(audit_type=mode).counters() == (0, 0, 0)

    def test_the_active_name_comes_from_the_chain_too(self):
        manager = AuditManager(audit_type="auto")
        manager._failover_service._current_index = 1

        assert manager.active_name() == "standard_audit"
