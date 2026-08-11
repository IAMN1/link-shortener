"""
Which implementations each configured mode actually builds.

Nothing held the audit half before. Every test configuration switches
logging and auditing off, so the branch that turns a mode into a list of
implementations was reached by almost nothing. Measured against the suite
as it stood when this file was written -- with it removed, 1665 tests, and
before ``test_managers_wire_the_failover_service`` existed, which now
catches the first of these as well:

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

from link_shortener.infrastructure.logging.handlers.audit.null_audit import (
    NullAuditLogger,
)
from link_shortener.infrastructure.logging.handlers.audit.standard import (
    StandardAuditLogger,
)
from link_shortener.infrastructure.logging.handlers.audit.structlog import (
    StructlogAuditLogger,
)
from link_shortener.infrastructure.logging.handlers.logger.null_logger import (
    NullLogger,
)
from link_shortener.infrastructure.logging.handlers.logger.standard import (
    StandardLogger,
)
from link_shortener.infrastructure.logging.handlers.logger.structlog import (
    StructLogger,
)
from link_shortener.infrastructure.logging.managers.audit_manager import (
    AuditManager,
)
from link_shortener.infrastructure.logging.managers.logger_manager import (
    LoggerManager,
)


def build_logger(mode: str) -> LoggerManager:
    """
    Build a ``LoggerManager`` without its background checker.

    The interval is switched off because nothing in this file asks about
    timing, and a manager left with the default starts a daemon thread in
    its constructor that nobody stops: measured, this directory alone left
    twelve ``_periodic_check`` threads alive at the end of the session.
    What the thread does when it is wanted is held by
    ``test_managers_wire_the_failover_service``.

    Args:
        mode: The configured ``LOGGER_TYPE``.

    Returns:
        The manager.
    """
    return LoggerManager(logger_type=mode, failover_check_interval=None)


def build_audit(mode: str) -> AuditManager:
    """
    Build an ``AuditManager`` without its background checker.

    Args:
        mode: The configured ``AUDIT_TYPE``.

    Returns:
        The manager.
    """
    return AuditManager(audit_type=mode, failover_check_interval=None)


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
        assert chain_of(build_logger(mode)) == expected

    def test_null_builds_one_implementation_and_no_failover(self):
        """One implementation is not a chain, and must not become one."""
        manager = build_logger("null")

        assert manager._failover_service is None
        assert type(manager._active_logger).__name__ == "NullLogger"

    def test_an_unknown_mode_falls_back_to_the_default_pair(self):
        """Unrecognised is not the same as off.

        A typo must not silently disable logging; it gets what ``auto``
        gets, which is what this branch always did.
        """
        assert chain_of(build_logger("nonsense")) == [
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
        assert chain_of(build_audit(mode)) == expected

    def test_null_writes_nothing_and_builds_no_failover(self):
        manager = build_audit("null")

        assert manager._failover_service is None
        assert type(manager._active_audit_logger).__name__ == "NullAuditLogger"

    def test_an_unknown_mode_falls_back_to_the_default_pair(self):
        """The logger chain had this test and the audit chain did not.

        Measured: the audit ``else`` branch returning ``["null"]`` left the
        whole suite green, and a typo in ``AUDIT_TYPE`` -- ``structlogg``,
        ``syslog``, an empty value -- then wrote no audit record at all,
        for any link created, followed or deleted. Nothing says so either:
        the counters read 0/0/0, because a chain that was never built
        cannot drop a call, and the only word on the health body is
        ``audit.active``.
        """
        assert chain_of(build_audit("nonsense")) == [
            "structlog_audit", "standard_audit"
        ]

    @pytest.mark.parametrize("spelling", ["structlogg", "syslog", ""])
    def test_a_typo_does_not_switch_auditing_off(self, spelling):
        """
        Args:
            spelling: A value no branch recognises.
        """
        assert chain_of(build_audit(spelling)) == [
            "structlog_audit", "standard_audit"
        ]


class TestOffMeansOffWhateverTheSpelling:
    """The case that turned a switch-off into a full audit trail."""

    @pytest.mark.parametrize("spelling", ["NULL", "Null", " null ", "nUlL"])
    def test_null_is_recognised_however_it_is_written(self, spelling):
        """Exact-string comparison sent all of these to the default.

        The default is the full chain, so an operator who wrote
        ``AUDIT_TYPE=NULL`` to switch auditing off got original_url,
        remote_addr and user_id written down instead.
        """
        manager = build_audit(spelling)

        assert manager._failover_service is None
        assert type(manager._active_audit_logger).__name__ == "NullAuditLogger"

    @pytest.mark.parametrize("spelling", ["STANDARD", " standard"])
    def test_the_order_modes_are_recognised_too(self, spelling):
        """``STANDARD`` used to leave the order it was asking to reverse."""
        assert chain_of(build_logger(spelling)) == [
            "standard", "structlog"
        ]


class TestASlotHoldsTheImplementationItNames:
    """The names are labels; nothing checked what was behind them.

    Measured: building the ``standard`` slot with a ``StructLogger`` -- and
    the ``standard_audit`` slot with a ``StructlogAuditLogger`` -- left the
    whole suite green. What that costs is the standby: the failure that
    takes the primary down takes its twin down with it, ``execute`` walks
    the whole list and answers ``ALL_SERVICES_FAILED``, every line is lost
    and ``/api/v1/admin/health`` reports ``active: "standard"`` -- so the
    operator reads that the standby took over from a chain that has
    nothing left to take over.
    """

    IMPLEMENTATION_OF = {
        "structlog": StructLogger,
        "standard": StandardLogger,
        "null": NullLogger,
        "structlog_audit": StructlogAuditLogger,
        "standard_audit": StandardAuditLogger,
        "null_audit": NullAuditLogger,
    }

    @pytest.mark.parametrize("mode", ["auto", "structlog", "standard"])
    def test_the_logger_chain_holds_what_it_names(self, mode):
        """
        Args:
            mode: The configured ``LOGGER_TYPE``.
        """
        for service, name in build_logger(mode)._failover_service._services:
            assert isinstance(service, self.IMPLEMENTATION_OF[name])

    @pytest.mark.parametrize("mode", ["auto", "structlog", "standard"])
    def test_the_audit_chain_holds_what_it_names(self, mode):
        """
        Args:
            mode: The configured ``AUDIT_TYPE``.
        """
        for service, name in build_audit(mode)._failover_service._services:
            assert isinstance(service, self.IMPLEMENTATION_OF[name])

    @pytest.mark.parametrize("mode", ["auto", "structlog", "standard"])
    def test_the_two_slots_are_not_the_same_implementation(self, mode):
        """A chain of one thing twice is a chain with no standby at all.

        Held apart from the check above because a mapping that named both
        slots after one class would satisfy it.

        Args:
            mode: The configured type, for either manager.
        """
        for manager in (build_logger(mode), build_audit(mode)):
            kinds = {
                type(service)
                for service, _name in manager._failover_service._services
            }
            assert len(kinds) == 2


class TestTheNameTheOperatorIsGivenIsTheOneDoingTheWork:
    """``active`` on the health body, and the only word about the move.

    ``AuditManager.active_name`` had this test; ``LoggerManager`` did not.
    Measured: reading ``_services[0][1]`` instead of the current one left
    the suite green, and with it every surface an operator has --
    ``/api/v1/admin/health`` and the line at start-up both report the
    primary forever, so a chain that handed its work down looks exactly
    like one that never did.
    """

    def test_the_logger_name_follows_the_work(self):
        manager = build_logger("auto")
        manager._failover_service._current_index = 1

        assert manager.get_active_logger_name() == "standard"

    def test_the_audit_name_follows_the_work(self):
        manager = build_audit("auto")
        manager._failover_service._current_index = 1

        assert manager.active_name() == "standard_audit"


class TestTheCountersComeFromTheChain:
    """``counters()`` can be made to answer zero, and nothing noticed.

    Measured: replacing both bodies with ``return 0, 0, 0`` left the whole
    suite green -- on the numbers introduced precisely so that "records
    are being lost" stops looking like "everything is fine". The reason is
    that every other test reads them off a ``FailoverService`` built by
    hand; nothing read them through a manager.
    """

    def test_a_manager_reports_what_its_failover_service_holds(self):
        manager = build_logger("auto")
        service = manager._failover_service
        assert service is not None

        service._dropped_calls = 7
        service._failed_checks = 3
        service._lost_log_lines = 5

        assert manager.counters() == (7, 3, 5)

    def test_an_audit_manager_does_the_same(self):
        manager = build_audit("auto")
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
        assert build_logger(mode).counters() == (0, 0, 0)
        assert build_audit(mode).counters() == (0, 0, 0)

    def test_the_active_name_comes_from_the_chain_too(self):
        manager = build_audit("auto")
        manager._failover_service._current_index = 1

        assert manager.active_name() == "standard_audit"
