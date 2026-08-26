"""What the service does when a journal file cannot be opened.

A file handler opens its file while it is being built, so a path that
will not open raised out of ``setup_logging``, out of ``create_app`` and
out of the process. Measured on the live stack with
``datas/logs/application.log`` replaced by a directory: the container sat
in ``Restarting (1)``, the public ``/health`` answered ``000``, gunicorn
said ``Worker failed to boot`` three times and stopped, and ``flask
maintenance health`` -- the command an operator runs at exactly that
moment -- ended in an ``IsADirectoryError`` traceback instead of a table.

That is the failure the whole failover exists to survive, arriving one
step before failover can see it. ``dockers/logrotate.conf`` promises the
opposite in as many words: "a file the application cannot write to: the
write fails, `FailoverService` counts it in `dropped_calls`".

So the journal that will not open is left out, the process keeps the
journals that did open, and every surface says which is which.
"""

import logging
import os

import pytest

from link_shortener.infrastructure.logging.bootstrap import (
    journals_unavailable, journals_written, setup_logging,
)
from link_shortener.infrastructure.logging.logging_settings import (
    LoggingSettings,
)


@pytest.fixture
def configure(tmp_path):
    """
    Configure logging the way ``create_app`` does, into a temporary directory.

    Args:
        tmp_path: Directory for the log files, per test.

    Yields:
        A callable taking the settings that differ from the deployment's
        and configuring logging with them.
    """
    root = logging.getLogger()
    audit = logging.getLogger("audit")
    # `propagate` among them, as the fixtures next door already save it:
    # it decides whether an audit record travels up into the application
    # journal, and a mode that leaves it false hands that answer to
    # whatever runs next.
    saved = (
        root.handlers[:], root.level,
        audit.handlers[:], audit.level, audit.propagate,
    )

    def configuring(**overrides):
        fields = {
            "log_dir": str(tmp_path),
            "log_file_name": "application",
            "audit_log_filename": "audit",
            "error_log_filename": "error",
            "log_date_format": "%Y-%m-%d %H:%M:%S",
            # The deployment this is about: files are the journal and the
            # console is off, so a file that will not open is the whole
            # of what is written.
            "log_to_console": False,
            "log_to_file": True,
            "log_level_str": "INFO",
            "debug": False,
            "sqlalchemy_log_level": "WARNING",
            "werkzeug_log_level": "WARNING",
            "logger_type": "auto",
            "logging_enabled": True,
            "audit_enabled": True,
        }
        fields.update(overrides)
        settings = LoggingSettings(**fields)
        setup_logging(settings)
        return settings

    yield configuring

    (root.handlers, root.level,
     audit.handlers, audit.level, audit.propagate) = saved


def block(path):
    """
    Put something in a journal's place that cannot be opened as a file.

    A directory, because that is what the live measurement used and what
    a mistaken bind mount actually leaves behind. The error it raises,
    ``IsADirectoryError``, is an ``OSError`` like every other way a path
    refuses -- a mode, a full disk, a name too long.

    Args:
        path: Where the journal file would be.
    """
    os.makedirs(path, exist_ok=True)


class TestTheProcessSurvivesIt:

    def test_the_application_journal_does_not_end_the_process(
        self, configure, tmp_path
    ):
        block(tmp_path / "application.log")

        configure()

        assert [entry.journal for entry in journals_unavailable()] == [
            "application"
        ]

    def test_the_audit_journal_does_not_end_the_process(
        self, configure, tmp_path
    ):
        """The audit chain is built after the other two and refuses alike."""
        block(tmp_path / "audit.log")

        configure()

        assert [entry.journal for entry in journals_unavailable()] == ["audit"]

    def test_the_journals_that_opened_are_still_written(
        self, configure, tmp_path
    ):
        """
        The point of surviving it: two journals of three is not none.

        A process that answers requests without an application journal
        still writes its errors, and that file is the one an operator
        reads first.
        """
        block(tmp_path / "application.log")

        configure()
        logging.getLogger("test").error("after the journal was refused")

        written = (tmp_path / "error.log").read_text(encoding="utf-8")
        assert "after the journal was refused" in written
        assert "error" in journals_written()
        assert "application" not in journals_written()

    def test_the_reason_names_the_path_and_the_cause(
        self, configure, tmp_path
    ):
        """
        Both halves, because neither alone tells an operator what to do.

        "The journal is unavailable" does not say whether to fix a
        directory, a mode or a disk, and the cause without the path does
        not say which of three files it was.
        """
        block(tmp_path / "application.log")

        configure()

        reason = journals_unavailable()[0].reason
        assert "application.log" in reason
        assert "Is a directory" in reason


class TestNothingIsWrittenIntoSilence:
    """
    A logger left with no handlers at all is worse than a missing file.

    The standard library answers that with ``lastResort``: warnings and
    worse, to stderr, unformatted -- and everything below a warning goes
    nowhere with nothing said. So a journal that refused and a console
    that was switched off leave the console switched back on.
    """

    def test_the_root_logger_keeps_somewhere_to_write(
        self, configure, tmp_path
    ):
        block(tmp_path / "application.log")
        block(tmp_path / "error.log")

        configure()

        assert logging.getLogger().handlers != []

    def test_the_audit_logger_keeps_somewhere_to_write(
        self, configure, tmp_path
    ):
        block(tmp_path / "audit.log")

        configure()

        assert logging.getLogger("audit").handlers != []

    def test_silence_asked_for_is_silent_on_purpose(self, configure, capsys):
        """
        Neither files nor console is a configuration, not a failure.

        The console comes back only where a journal refused to open --
        giving one to a deployment that asked for no output would be this
        rule inventing output nobody wanted. But "no handlers" is not
        silence either: the standard library answers a handler-less
        logger with ``lastResort``, which writes ``WARNING`` and worse to
        stderr formatted by nothing, whatever ``LOGGER_TYPE`` asked for.
        Measured before the ``NullHandler``: an ``error`` record arrived
        on stderr as the bare line, on a deployment with both
        destinations switched off.
        """
        configure(log_to_file=False, log_to_console=False)

        logging.getLogger("probe").error("an error nobody asked to see")
        logging.getLogger("audit").error("an audit line nobody asked to see")

        assert capsys.readouterr().err == ""
        assert all(
            isinstance(handler, logging.NullHandler)
            for handler in logging.getLogger().handlers
        )
        assert all(
            isinstance(handler, logging.NullHandler)
            for handler in logging.getLogger("audit").handlers
        )

    def test_a_console_nobody_asked_for_is_not_added(self, configure):
        """
        The other direction, and the one that makes the rule a rule.

        A deployment that switched the console off and keeps its files
        does not get a console back. Otherwise every container would
        write its journal twice -- once to the file, once to the
        collector reading stdout -- for a fault that never happened.
        """
        configure()

        assert [
            handler for handler in logging.getLogger().handlers
            if isinstance(handler, logging.StreamHandler)
            and not isinstance(handler, logging.FileHandler)
        ] == []


class TestTheAnswerIsAboutThisConfiguration:

    def test_configuring_again_forgets_what_the_last_one_could_not_open(
        self, configure, tmp_path
    ):
        """
        A path fixed between two calls is a path that opens.

        Without this the answer would accumulate: a worker reconfigured
        after the directory was replaced by a file would go on reporting
        a journal that is being written.
        """
        blocked = tmp_path / "application.log"
        block(blocked)
        configure()

        os.rmdir(blocked)
        configure()

        assert journals_unavailable() == ()
        assert "application" in journals_written()

    def test_a_deployment_that_writes_no_files_reports_neither(
        self, configure
    ):
        """
        ``LOG_TO_FILE=false`` is a configuration, not a fault.

        Nothing failed to open, and nothing is being written: the two
        lists are both empty, and it is the second that tells this state
        from a healthy one. Reading failures alone put "every journal is
        fine" on the screen of a deployment with no journals -- the
        sentence ``cache_configured`` was added to stop the same answer
        making about Redis.
        """
        configure(log_to_file=False, log_to_console=True)

        assert journals_unavailable() == ()
        assert journals_written() == ()
