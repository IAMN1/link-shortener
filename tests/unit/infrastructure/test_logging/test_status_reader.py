"""
The reader that puts the chain counters on the health endpoint.

``ComponentLoggingStatus`` is the only thing between the two components and
the ``logging`` section of ``GET /api/v1/admin/health``, and nothing tested
it: the controller test builds ``LoggingStatus`` by hand, so a reader that
swapped the logger's counters for the audit's, or reported one chain twice,
would go through green: swapping the two triples in ``read()`` passes
everything else.

What each component answers is that component's own test below. The reader
used to work it out itself, off a private ``_manager`` attribute it took
from both of them.
"""

import os

import pytest

from link_shortener.application.ports.logging_status import (
    ChainStatus, NOT_STARTED,
)
from link_shortener.infrastructure.di.components.audit import AuditComponent
from link_shortener.infrastructure.di.components.logger import LoggerComponent
from link_shortener.infrastructure.logging.status_reader import (
    ComponentLoggingStatus,
)


class FakeComponent:
    """A component answering for its chain, as the DI ones do."""

    def __init__(self, status):
        """
        Args:
            status: The ``ChainStatus`` to report.
        """
        self._status = status

    def chain_status(self):
        """Return what this component reports about its chain."""
        return self._status


class TestEachChainIsReportedAsItself:

    @pytest.fixture
    def status(self):
        """Two chains whose every number differs from the other's."""
        return ComponentLoggingStatus(
            FakeComponent(ChainStatus("structlog", 1, 2, 3, "healthy")),
            FakeComponent(
                ChainStatus("structlog_audit", 4, 5, 6, "unhealthy")
            ),
        ).read()

    def test_the_logger_counters_are_the_logger_manager_s(self, status):
        assert status.logger.active == "structlog"
        assert (
            status.logger.dropped_calls,
            status.logger.failed_checks,
            status.logger.lost_log_lines,
        ) == (1, 2, 3)

    def test_each_chain_keeps_its_own_finding(self, status):
        """
        The state no counter beside it can report.

        Distinct between the chains for the reason every number here is:
        one finding repeated is a reader that can publish either chain's
        under both names and still look right.
        """
        assert (status.logger.last_check, status.audit.last_check) == (
            "healthy", "unhealthy"
        )

    def test_the_audit_counters_are_the_audit_manager_s(self, status):
        """Every number distinct from the logger's, so a reader reporting
        one chain under both names cannot come out looking right."""
        assert status.audit.active == "structlog_audit"
        assert (
            status.audit.dropped_calls,
            status.audit.failed_checks,
            status.audit.lost_log_lines,
        ) == (4, 5, 6)

    def test_the_process_holding_them_is_named(self, status):
        """
        The counters are one worker's, and a deployment runs several.

        Measured on the running stack after one broken journal: twelve
        requests to ``/api/v1/admin/health``, in one state of one
        service, answered ``dropped_calls`` 16, 27, 28 and 6 -- by which
        worker happened to take each request. A worker that served no
        traffic during the outage answers zero, which is exactly the
        "everything is fine" this section exists to end.
        """
        assert status.worker == os.getpid()


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
            LoggerComponent(
                logging_enabled=True, logger_type="auto",
                failover_check_interval=None,
            ),
            AuditComponent(
                audit_enabled=True, audit_type="auto",
                failover_check_interval=None,
            ),
        ).read()

        assert status.logger.active == "not started"
        assert status.audit.active == "not started"
        assert status.logger.lost_log_lines == 0
        assert status.audit.lost_log_lines == 0
        # A chain nobody built has had no round to find anything, which
        # is not the finding "well": the two read alike from the zeroes
        # alone, and only this word tells them apart.
        assert status.logger.last_check == "not run"
        assert status.audit.last_check == "not run"

    def test_one_chain_started_does_not_start_the_other(self):
        audit = AuditComponent(
            audit_enabled=True, audit_type="auto", failover_check_interval=None,
        )
        logger = LoggerComponent(
            logging_enabled=True, logger_type="null", failover_check_interval=None,
        )
        logger.get_logger(__name__)
        try:
            status = ComponentLoggingStatus(logger, audit).read()

            assert status.logger.active == "null"
            assert status.audit.active == NOT_STARTED
        finally:
            logger.shutdown()
            audit.shutdown()

    def test_asking_does_not_build_the_chain(self):
        """
        A health check is not a request for a logger.

        Building one here would start a background thread and a pair of
        file handlers on every call to ``/api/v1/admin/health`` -- an
        endpoint an orchestrator polls.
        """
        component = LoggerComponent(
            logging_enabled=True, logger_type="auto",
            failover_check_interval=None,
        )

        component.chain_status()

        assert component._manager is None


class TestTheComponentsSpeakOneVocabulary:
    """One question, one word for the answer.

    The DI component answered ``unknown`` where the reader beside it
    answered ``not started``, about the same chain in the same state.
    """

    def test_the_name_a_component_gives_is_the_name_it_reports(self):
        component = LoggerComponent(
            logging_enabled=True, logger_type="auto",
            failover_check_interval=None,
        )

        assert component.get_active_logger_name() == NOT_STARTED
        assert component.chain_status().active == NOT_STARTED
