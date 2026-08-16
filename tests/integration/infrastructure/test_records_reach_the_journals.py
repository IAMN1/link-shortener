"""That a record actually lands in a file, under every mode there is.

Nothing in the suite had ever read a journal back. The `testing` profile
sets `LOG_TO_FILE = False`, so every test in every other file logs to
nowhere; what is held elsewhere is which implementations a mode *builds*
(`test_chain_composition.py`), that they report themselves healthy
(`test_logging_health.py`), and that a failed write reaches the caller
(`test_write_failures_reach_the_caller.py`). None of that is the same
statement as "the sentence is in `application.log` afterwards", and the
gap is exactly where a formatter, a level or a handler goes wrong without
anything noticing.

Two things are asked here, per mode:

  - an ordinary record, an error and an audit event each reach the journal
    they belong in, and `null` writes nothing at all -- which is what an
    operator who switched logging off is entitled to;
  - after the active implementation starts refusing calls, the *next*
    record is on disk. The chain moving is already checked elsewhere by
    the name it reports; that a record survives the move is not, and a
    chain that switches cleanly while dropping the sentence it switched
    for would pass every existing check.

Both were driven by hand across four profiles and four modes when the
worker's logging changed, found nothing, and are kept here rather than as
a third live run: a script nobody runs rots, and these fit in a file that
runs on every commit.
"""

import logging

import pytest

from link_shortener.infrastructure.logging.bootstrap import setup_logging
from link_shortener.infrastructure.logging.logging_settings import (
    LoggingSettings,
)
from link_shortener.infrastructure.logging.managers.audit_manager import (
    AuditManager,
)
from link_shortener.infrastructure.logging.managers.logger_manager import (
    LoggerManager,
)


WRITING_MODES = ("auto", "structlog", "standard")
"""The modes that build a real implementation. ``null`` is asked the
opposite question below."""


def refuse(*_args, **_kwargs):
    """What an implementation that cannot write looks like from the chain.

    ``ENOSPC`` rather than a bare exception because that is the failure
    the failover service exists for: a full disk, or a volume that went
    away under a running process.
    """
    raise OSError(28, "No space left on device")


@pytest.fixture
def journals(tmp_path):
    """
    Configure logging into a temporary directory and hand back the chains.

    Args:
        tmp_path: Directory the journals are written to, per test.

    Yields:
        A callable taking a mode and returning the directory, the logger
        chain's manager and the audit chain's manager.
    """
    root = logging.getLogger()
    audit = logging.getLogger("audit")
    saved = (
        root.handlers[:], root.level,
        audit.handlers[:], audit.level, audit.propagate,
    )
    built = []

    def configure(mode: str = "auto"):
        settings = LoggingSettings(
            log_dir=str(tmp_path),
            log_file_name="application",
            audit_log_filename="audit",
            error_log_filename="error",
            log_date_format="%Y-%m-%d %H:%M:%S",
            log_to_console=False,
            log_to_file=True,
            log_level_str="INFO",
            debug=False,
            sqlalchemy_log_level="WARNING",
            werkzeug_log_level="WARNING",
            logger_type=mode,
            audit_enabled=True,
        )
        setup_logging(settings, logging_enabled=True, audit_enabled=True)

        # The interval is long rather than default: the background probe
        # would otherwise wake up mid-test and move a chain this file is
        # about to move on purpose.
        logger_manager = LoggerManager(mode, failover_check_interval=3600)
        audit_manager = AuditManager(mode, failover_check_interval=3600)
        built.extend((logger_manager, audit_manager))
        return tmp_path, logger_manager, audit_manager

    yield configure

    for manager in built:
        manager.shutdown()
    root.handlers[:], root.level = saved[0], saved[1]
    audit.handlers[:], audit.level, audit.propagate = saved[2], saved[3], saved[4]


def read(directory, name):
    """
    The text of one journal, or an empty string if it was never created.

    Args:
        directory: Where the journals are.
        name: File name without the extension.

    Returns:
        What the file holds.
    """
    path = directory / f"{name}.log"
    return path.read_text(encoding="utf-8") if path.exists() else ""


class TestARecordEndsUpInItsJournal:

    @pytest.mark.parametrize("mode", WRITING_MODES)
    def test_an_ordinary_record_reaches_the_application_journal(self, mode, journals):
        directory, manager, _audit = journals(mode)

        manager.get_logger("live.check").info("an ordinary record")

        assert "an ordinary record" in read(directory, "application")

    @pytest.mark.parametrize("mode", WRITING_MODES)
    def test_an_error_reaches_the_error_journal(self, mode, journals):
        """
        The error journal takes ``ERROR`` and above and nothing else, so
        this is two statements: the record is there, and the ordinary one
        beside it is not.
        """
        directory, manager, _audit = journals(mode)
        logger = manager.get_logger("live.check")

        logger.info("an ordinary record")
        logger.error("a record that belongs in the error journal")

        written = read(directory, "error")
        assert "belongs in the error journal" in written
        assert "an ordinary record" not in written

    @pytest.mark.parametrize("mode", WRITING_MODES)
    def test_an_audit_event_reaches_the_audit_journal(self, mode, journals):
        """
        And only there: the audit logger does not propagate, which is what
        keeps the record an incident is reconstructed from out of the
        journal that traffic fills.
        """
        directory, _manager, audit_manager = journals(mode)

        audit_manager.get_audit_logger().log_url_created(
            short_code="abc1234", original_url="https://example.com/audited"
        )

        assert "example.com/audited" in read(directory, "audit")
        assert "example.com/audited" not in read(directory, "application")


class TestNullWritesNothingOfTheApplicationS:
    """
    The opposite question, and the reason it is worth asking: `null` is
    what an operator sets to switch logging off, and a mode that quietly
    goes on writing is the same defect as one that quietly stops.

    "Nothing" means nothing the application logs. The journal is not empty
    afterwards: `setup_logging` installs the handlers whatever the mode is
    and writes one line about itself through them, because the mode
    chooses an implementation for the *chain* and `LOGGING_ENABLED` is the
    switch that takes the handlers away. Asserting an empty file instead
    was this file's own first mistake, and it would have pinned the
    bootstrap line as forbidden rather than the records that matter.
    """

    def test_no_record_of_the_application_is_written(self, journals):
        directory, manager, audit_manager = journals("null")

        logger = manager.get_logger("live.check")
        logger.info("an ordinary record")
        logger.error("a record that would have been an error")
        audit_manager.get_audit_logger().log_url_created(
            short_code="abc1234", original_url="https://example.com/audited"
        )

        assert "an ordinary record" not in read(directory, "application")
        assert "would have been an error" not in read(directory, "error")
        assert "example.com/audited" not in read(directory, "audit")

    def test_what_is_in_the_journal_is_the_bootstrap_line_and_nothing_else(
        self, journals
    ):
        """Said out loud, so that the line above is read as a boundary
        rather than as an exception somebody may widen."""
        directory, manager, _audit = journals("null")

        manager.get_logger("live.check").info("an ordinary record")

        written = [line for line in read(directory, "application").splitlines() if line]
        assert len(written) == 1
        assert "Logging has been initialized" in written[0]


class TestTheRecordSurvivesAFailover:
    """
    A chain that switches cleanly and loses the record it switched for
    passes every check that reads a name instead of a file.
    """

    @pytest.mark.parametrize("mode", WRITING_MODES)
    def test_the_next_record_is_on_disk_after_the_active_one_refuses(
        self, mode, journals
    ):
        directory, manager, _audit = journals(mode)
        logger = manager.get_logger("live.check")
        service = manager._failover_service
        moved_from = manager.get_active_logger_name()

        service._services[service._current_index][0].info = refuse
        logger.info("written after the first implementation refused")

        assert manager.get_active_logger_name() != moved_from
        assert (
            "written after the first implementation refused"
            in read(directory, "application")
        )

    @pytest.mark.parametrize("mode", WRITING_MODES)
    def test_a_refusal_by_every_implementation_is_counted(self, mode, journals):
        """
        The other end of the same chain: when nobody can take the record,
        the loss is a number an operator can read rather than a silence.
        ``dropped_calls`` is what `/api/v1/admin/health` reports.
        """
        directory, manager, _audit = journals(mode)
        logger = manager.get_logger("live.check")
        service = manager._failover_service

        for implementation, _name in service._services:
            implementation.info = refuse
        logger.info("a record nobody can take")

        dropped, _failed_checks, _lost = manager.counters()
        assert dropped == 1
        assert "a record nobody can take" not in read(directory, "application")
