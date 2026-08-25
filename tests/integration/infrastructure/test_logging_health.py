"""What the health probe answers on the logging this application sets up.

The failover service asks ``is_healthy()`` and now hands the work down on a
``False``. Every test that had ever asked the question attached a handler
directly to the logger under test -- a wiring this application does not use.
``setup_logging`` puts the handlers on the root logger and lets named loggers
propagate to it, so ``logger.handlers`` is empty for everything
``LoggerManager`` builds, and a probe reading that alone answered ``False``
for a logger whose records were arriving.

The consequence was not hypothetical: with ``LOGGER_TYPE=standard`` the
background check would take the work off the operator's chosen logger one
interval after start-up and never give it back, because the same probe would
go on answering ``False``.
"""

import logging

import pytest

from link_shortener.infrastructure.logging.bootstrap import setup_logging
from link_shortener.infrastructure.logging.handlers.raising import (
    OWN_LOGGER_NAMES,
)
from link_shortener.infrastructure.logging.managers.audit_manager import (
    AuditManager,
)
from link_shortener.infrastructure.logging.handlers.audit.standard import (
    StandardAuditLogger,
)
from link_shortener.infrastructure.logging.handlers.audit.structlog import (
    StructlogAuditLogger,
)
from link_shortener.infrastructure.logging.handlers.logger.standard import (
    StandardLogger,
)
from link_shortener.infrastructure.logging.handlers.logger.structlog import (
    StructLogger,
)
from link_shortener.infrastructure.logging.logging_settings import (
    LoggingSettings,
)
from link_shortener.application.ports.journal_reader import (
    HEALTH_PROBE_EVENT_TYPE,
)
from link_shortener.infrastructure.logging.utils import (
    HEALTH_PROBE_FIELDS, HEALTH_PROBE_MESSAGE, probe_level,
)
from link_shortener.infrastructure.logging.managers.logger_manager import (
    LoggerManager,
)


@pytest.fixture
def configured_logging(tmp_path):
    """
    Configure logging the way ``create_app`` does, into a temporary directory.

    Args:
        tmp_path: Directory for the log files, per test.

    Yields:
        A callable taking a logger type and a journal level, and
        configuring logging for them.
    """
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level

    def configure(logger_type: str = "auto", log_level_str: str = "INFO"):
        settings = LoggingSettings(
            log_dir=str(tmp_path),
            log_file_name="link_shortener",
            audit_log_filename="audit",
            error_log_filename="error",
            log_date_format="%Y-%m-%d %H:%M:%S",
            log_to_console=False,
            log_to_file=True,
            log_level_str=log_level_str,
            debug=False,
            sqlalchemy_log_level="WARNING",
            werkzeug_log_level="WARNING",
            logger_type=logger_type,
            audit_enabled=True,
        )
        setup_logging(settings, logging_enabled=True, audit_enabled=True)

    yield configure

    root.handlers = saved_handlers
    root.setLevel(saved_level)


class TestHealthOnTheRealWiring:

    def test_the_named_logger_owns_no_handlers(self, configured_logging):
        # The premise of everything below, asserted rather than assumed: if
        # this ever changes the tests after it stop being about anything.
        configured_logging()

        assert logging.getLogger("global").handlers == []

    @pytest.mark.parametrize("logger_type", ["auto", "standard", "structlog"])
    def test_both_implementations_report_themselves_well(
        self, configured_logging, logger_type
    ):
        configured_logging(logger_type)

        assert StandardLogger(name="global").is_healthy() is True
        assert StructLogger(name="global").is_healthy() is True

    def test_both_audit_implementations_report_themselves_well(
        self, configured_logging
    ):
        configured_logging()

        assert StandardAuditLogger(name="audit").is_healthy() is True
        assert StructlogAuditLogger().is_healthy() is True

    def test_every_implementation_writes_under_a_name_of_this_application(
        self, configured_logging
    ):
        """The name decides whether a failed write is heard at all.

        ``_RaisesForOwnRecords`` lets an ``OSError`` out of a write only
        for records whose logger belongs to this application
        (``OWN_LOGGER_NAMES``); everything else keeps the standard
        library's behaviour, which is to swallow the failure in
        ``handleError``. So an implementation built under any other name --
        ``StructLogger(name="structlog")``, ``StandardAuditLogger(
        name="standard_audit")`` -- goes on being asked for records that
        quietly go nowhere: no exception, no demotion, ``dropped_calls``
        at zero, ``/api/v1/admin/health`` reporting the chain as active.
        Each of those two renamings passes everything else, and moves the
        audit trail from ``audit.log`` into the application log with it.

        Read off the implementations the managers actually build, not off
        constructors called here: the renaming that survives is one made
        inside a manager.
        """
        configured_logging("auto")
        written = []

        class Catcher(logging.Handler):
            """Remembers the logger name of every record that arrives."""

            def emit(self, record):
                written.append(record.name)

        catcher = Catcher()
        # Both, because the audit tree does not propagate to the root.
        root = logging.getLogger()
        audit_tree = logging.getLogger("audit")
        root.addHandler(catcher)
        audit_tree.addHandler(catcher)
        try:
            loggers = LoggerManager(
                logger_type="auto", failover_check_interval=None
            )
            for implementation, _name in loggers._failover_service._services:
                implementation.info("probe")

            audits = AuditManager(
                audit_type="auto", failover_check_interval=None
            )
            for implementation, _name in audits._failover_service._services:
                implementation.log_url_created("abc123", "https://example.com")
        finally:
            root.removeHandler(catcher)
            audit_tree.removeHandler(catcher)

        assert len(written) == 4, (
            f"four implementations, {len(written)} records: {written}"
        )
        assert [
            name for name in written
            if name.split(".")[0] not in OWN_LOGGER_NAMES
        ] == []

    @pytest.mark.parametrize("logger_type", ["auto", "standard"])
    def test_a_check_leaves_the_work_where_the_operator_put_it(
        self, configured_logging, logger_type
    ):
        # The whole round, on the chain the manager actually builds. A probe
        # that answers False for a working logger shows up here as the work
        # moving on the first check after start-up.
        configured_logging(logger_type)
        manager = LoggerManager(logger_type=logger_type, failover_check_interval=None)
        failover = manager._failover_service
        assert failover is not None, "the chain was not built"
        chosen = failover.get_current_service_name()

        failover._run_check()
        failover._run_check()

        assert failover.get_current_service_name() == chosen


class Jammed:
    """A stream that refuses every write, the way a full volume does."""

    def write(self, text):
        raise OSError(28, "No space left on device")

    def flush(self):
        """Nothing is buffered, because nothing was ever written."""

    def close(self):
        """Closing costs nothing; the handlers are given back by fixture."""


def jam(logger_name: str) -> None:
    """
    Make every handler a record from this logger reaches refuse its writes.

    Walks the hierarchy the way a record does -- up through the parents,
    stopping where ``propagate`` is false -- because that is where the
    handlers live: this application puts them on the root logger and on
    the audit tree, never on the named loggers themselves.

    Args:
        logger_name: The logger whose path to disable.
    """
    log = logging.getLogger(logger_name)
    while log:
        for handler in log.handlers:
            handler.stream = Jammed()
        if not log.propagate:
            break
        log = log.parent


class TestAProbeThatCannotWriteSaysSo:
    """
    The probe writes, so it has to write where the records go.

    It wrote at ``DEBUG``. Every handler carries a level of its own --
    ``LOG_LEVEL`` for the journal, ``INFO`` for the audit trail whatever
    ``LOG_LEVEL`` says -- and a record is dropped at the first level test
    it fails, so at the documented ``LOG_LEVEL=INFO`` the probe reached no
    handler at all. It could not fail, and it never did: measured on the
    running stack with the journal file replaced by a directory, four
    workers, two minutes of traffic -- zero ``Demoting`` lines, eight
    ``Upgrading`` lines, four of them onto the implementation that was
    refusing every write.

    Both halves of the failover service rest on this answer: the way down
    when the active implementation stops writing, and the way back up. With
    the probe unable to fail, the way down existed only through an
    exception in ``execute`` -- which is to say at the cost of a record --
    and the way up led back onto the broken implementation every cooldown.
    """

    def test_the_journal_chain_admits_it_cannot_write(self, configured_logging):
        configured_logging("auto")
        jam("global")

        assert StandardLogger(name="global").is_healthy() is False
        assert StructLogger(name="global").is_healthy() is False

    def test_the_audit_chain_admits_it_cannot_write(self, configured_logging):
        """The audit handlers are ``INFO`` whatever ``LOG_LEVEL`` says.

        So this chain's probe could not reach a handler under any
        configuration at all, and the trail that stopped being written
        went on reporting itself well.
        """
        configured_logging("auto")
        jam("audit")

        assert StandardAuditLogger(name="audit").is_healthy() is False
        assert StructlogAuditLogger().is_healthy() is False

    def test_a_working_chain_is_still_called_well(self, configured_logging):
        # The premise: without it the three assertions above are satisfied
        # by a probe that answers False to everything.
        configured_logging("auto")

        assert StandardLogger(name="global").is_healthy() is True
        assert StructLogger(name="global").is_healthy() is True
        assert StandardAuditLogger(name="audit").is_healthy() is True
        assert StructlogAuditLogger().is_healthy() is True

    def test_the_background_round_hands_the_work_down(self, configured_logging):
        """What the answer is for.

        ``_attempt_demotion`` exists so the work leaves an implementation
        that has stopped writing *before* a record is lost on it. It never
        ran: the probe it asks could not answer ``False``.
        """
        configured_logging("auto")
        manager = LoggerManager(logger_type="auto", failover_check_interval=None)
        failover = manager._failover_service
        assert failover is not None, "the chain was not built"

        primary, _ = failover._services[0]
        jam("global")
        # Only the active implementation is unwell; the standby is asked
        # the same question and has to answer for itself.
        failover._services[1] = (
            type("Well", (), {"is_healthy": lambda self: True})(), "standby"
        )

        failover._run_check()

        assert failover.get_current_service_name() == "standby", (
            f"the work stayed on {type(primary).__name__}"
        )


class TestTheProbeDoesNotFileItselfAsAFailure:
    """
    A probe writes, so where it writes matters.

    ``bootstrap`` sends every record of ``ERROR`` and above to
    ``error.log``, which is read as a list of things that went wrong and
    is what a monitor watches. Written at the journal's own level, the
    probe becomes an ``ERROR`` record on a deployment running
    ``LOG_LEVEL=ERROR`` -- both that and ``CRITICAL`` are accepted values
    -- and files a line there every check interval. Switching logging off
    is worse still: the root goes to ``CRITICAL`` outright, and the suite
    printed five ``[critical] logging chain health probe`` lines before
    the cap went in.
    """

    def _probe_every_chain(self):
        """Ask all four implementations how they are."""
        return [
            StandardLogger(name="global").is_healthy(),
            StructLogger(name="global").is_healthy(),
            StandardAuditLogger(name="audit").is_healthy(),
            StructlogAuditLogger().is_healthy(),
        ]

    def test_it_never_reaches_the_error_journal(
        self, configured_logging, tmp_path
    ):
        configured_logging("auto", log_level_str="ERROR")

        self._probe_every_chain()

        error_log = tmp_path / "error.log"
        written = error_log.read_text() if error_log.exists() else ""
        assert HEALTH_PROBE_MESSAGE not in written, written

    def test_it_reaches_the_journal_at_the_documented_level(
        self, configured_logging, tmp_path
    ):
        """The premise: the cap must not silence the probe where it works.

        ``LOG_LEVEL=INFO`` is what the deployment documents, and there the
        probe has to arrive -- otherwise the assertion above is satisfied
        by a probe that writes nowhere at all.
        """
        configured_logging("auto", log_level_str="INFO")

        self._probe_every_chain()

        journal = (tmp_path / "link_shortener.log").read_text()
        audit = (tmp_path / "audit.log").read_text()
        assert HEALTH_PROBE_MESSAGE in journal
        assert HEALTH_PROBE_MESSAGE in audit

    def test_it_is_never_written_above_a_warning(self, configured_logging):
        """Read off the level itself, over every value ``LOG_LEVEL`` takes.

        The journal test above cannot see a ``CRITICAL`` probe: logging
        switched off leaves a ``NullHandler`` and no file to read.
        """
        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            configured_logging("auto", log_level_str=level)

            assert probe_level("global") <= logging.WARNING, level
            assert probe_level("audit") <= logging.WARNING, level


class TestTheProbeIsMarkedSoAReaderCanBeSparedIt:
    """
    The probe writes into the journal it is probing, so it says what it is.

    ``JournalFilter`` drops ``LOGGING_CHAIN_PROBE`` from the plain tail and
    brings it back when the type is asked for by name. That only works if
    the record carries the type: unmarked, the probe is an ordinary line,
    and it filled 25 of the 50 lines on the first screen of the journals
    page -- measured on the running stack.

    The mark travels on the chain the journal is formatted for, which is
    the chain doing the work: the standby is not probed at all while the
    primary answers -- ``_attempt_demotion`` stops at a healthy active
    implementation and ``_attempt_upgrade`` returns at index zero -- so
    what reaches the file in normal running is the active chain's probe.
    """

    @pytest.mark.parametrize(
        "logger_type, journal",
        [("structlog", "link_shortener.log"), ("standard", "link_shortener.log")],
    )
    def test_the_active_journal_chain_marks_its_probe(
        self, configured_logging, tmp_path, logger_type, journal
    ):
        configured_logging(logger_type)
        active = (
            StructLogger(name="global") if logger_type == "structlog"
            else StandardLogger(name="global")
        )

        active.is_healthy()
        logging.shutdown()

        assert HEALTH_PROBE_EVENT_TYPE in (tmp_path / journal).read_text()

    def test_the_active_audit_chain_marks_its_probe(
        self, configured_logging, tmp_path
    ):
        configured_logging("auto")

        StructlogAuditLogger().is_healthy()
        logging.shutdown()

        assert HEALTH_PROBE_EVENT_TYPE in (tmp_path / "audit.log").read_text()

    def test_the_mark_is_the_one_the_filter_hides_by(self):
        """One constant, read from where the filter reads it.

        Written out twice -- once here and once in the filter -- the two
        would agree until somebody renamed one of them, and the page would
        quietly fill up again.
        """
        assert HEALTH_PROBE_FIELDS == {"event_type": HEALTH_PROBE_EVENT_TYPE}
