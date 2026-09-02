"""Every combination of the logging switches, held together.

Five settings decide what this application writes and where:
``LOGGING_ENABLED``, ``AUDIT_ENABLED``, ``LOG_TO_CONSOLE``,
``LOG_TO_FILE`` and ``LOGGER_TYPE``. They are documented as free to
combine, and each of them is read in a different place, so what holds
them together has to be one test that tries them all -- 64 combinations,
each asserting the three promises the settings make:

* the process starts, whatever was asked for;
* the console is in the shape ``LOGGER_TYPE`` names, and is silent when
  it was switched off;
* the files are JSON, whatever the console was asked to look like,
  because a program reads them.

The third is the one that cannot be left to a reader's eye: the two
logger types reach the files through different formatters -- a
``JSONFormatter`` for ``standard``, a structlog ``JSONRenderer`` for the
others -- and only one of them is the shape ``FileJournalReader`` parses.
"""

import itertools
import json
import logging

import pytest

from link_shortener.infrastructure.logging.bootstrap import setup_logging
from link_shortener.infrastructure.logging.logging_settings import (
    LoggingSettings,
)


MODES = list(itertools.product(
    (True, False),                                  # LOGGING_ENABLED
    (True, False),                                  # AUDIT_ENABLED
    (True, False),                                  # LOG_TO_CONSOLE
    (True, False),                                  # LOG_TO_FILE
    ("auto", "structlog", "standard", "null"),      # LOGGER_TYPE
))


@pytest.fixture
def configured(tmp_path):
    """
    Configure logging as ``create_app`` does, into a temporary directory.

    Args:
        tmp_path: Directory for the journals, per test.

    Yields:
        A callable taking the five switches and configuring logging.
    """
    root = logging.getLogger()
    audit = logging.getLogger("audit")
    # `propagate` among them: it is what decides whether an audit record
    # travels up into `application.log`, this file asserts on it, and a
    # mode that leaves it false hands that answer to the mode after it --
    # which is a test passing on the previous test's state.
    saved = (root.handlers[:], root.level,
             audit.handlers[:], audit.level, audit.propagate)

    def configure(logging_enabled, audit_enabled, to_console, to_file, logger_type):
        # Back to the standard library's own default before each mode, so
        # that what this mode does with it is what the assertions read.
        audit.propagate = True
        setup_logging(
            LoggingSettings(
                log_dir=str(tmp_path),
                log_file_name="application",
                audit_log_filename="audit",
                error_log_filename="error",
                log_date_format="%Y-%m-%d %H:%M:%S",
                log_to_console=to_console,
                log_to_file=to_file,
                log_level_str="INFO",
                debug=False,
                sqlalchemy_log_level="WARNING",
                werkzeug_log_level="WARNING",
                logger_type=logger_type,
                logging_enabled=logging_enabled,
                audit_enabled=audit_enabled,
            )
        )

    yield configure

    (root.handlers, root.level,
     audit.handlers, audit.level, audit.propagate) = saved


def journal_lines(path):
    """
    Read a journal, if this mode wrote one.

    Args:
        path: Where the journal would be.

    Returns:
        Its non-empty lines, or an empty list where there is no file.
    """
    if not path.exists():
        return []

    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.mark.parametrize("mode", MODES, ids=lambda mode: "-".join(map(str, mode)))
def test_the_mode_starts_and_writes_what_it_promised(mode, configured, tmp_path, capsys):
    """
    Args:
        mode: The five switches, as ``LOGGING_ENABLED``,
            ``AUDIT_ENABLED``, ``LOG_TO_CONSOLE``, ``LOG_TO_FILE``,
            ``LOGGER_TYPE``.
        configured: Configures logging for a mode.
        tmp_path: Where the journals go.
        capsys: Reads what reached the console.
    """
    logging_enabled, audit_enabled, to_console, to_file, logger_type = mode

    configured(*mode)
    logging.getLogger("probe").info("a line for the journal")
    logging.getLogger("probe").error("a line for the error journal")
    logging.getLogger("audit").info("an audit line")
    for handler in logging.getLogger().handlers + logging.getLogger("audit").handlers:
        handler.flush()

    console = capsys.readouterr()
    written = console.out + console.err

    # Every line of every file is a JSON object, whichever formatter the
    # logger type reached them through.
    for name in ("application", "audit", "error"):
        for line in journal_lines(tmp_path / f"{name}.log"):
            assert isinstance(json.loads(line), dict), f"{name}.log: {line[:80]}"

    if logging_enabled and to_file:
        assert journal_lines(tmp_path / "application.log"), "asked for a file, wrote none"
    else:
        assert not journal_lines(tmp_path / "application.log")

    if audit_enabled and to_file:
        assert journal_lines(tmp_path / "audit.log"), "audit asked for a file, wrote none"
    else:
        assert not journal_lines(tmp_path / "audit.log")

    # The two chains have their own switches, and the console is shared:
    # `LOGGING_ENABLED=false` with `AUDIT_ENABLED=true` is a deployment
    # that keeps its audit trail on screen and nothing else, which is a
    # supported answer rather than a leak.
    if logging_enabled and to_console:
        assert "a line for the journal" in written
    else:
        # Silence has to be on purpose. A logger with no handlers at all
        # is not silent: the standard library answers those records with
        # `lastResort`, which writes WARNING and worse to stderr,
        # formatted by nothing. Measured before the `NullHandler`: a
        # security event arrived on a container's stderr as a bare Python
        # dict, on a deployment that had switched both destinations off.
        assert "a line for the journal" not in written
        assert "a line for the error journal" not in written

    if audit_enabled and to_console:
        assert "an audit line" in written
    else:
        assert "an audit line" not in written

    # Switched off means written nowhere, not written elsewhere. A
    # `NullHandler` does not stop a record travelling: with `propagate`
    # left true an audit record goes up to the root and lands in
    # `application.log`, unmarked as audit and rotated as something else.
    # Measured with `AUDIT_ENABLED=false`: the record reached
    # `application.log` while `audit.log` was never created.
    if not audit_enabled:
        assert not logging.getLogger("audit").propagate
        for line in journal_lines(tmp_path / "application.log"):
            assert "an audit line" not in line, line[:90]

    if written.strip():
        # `standard` renders a line for a person to read; the structlog
        # types render their own, and neither renders the JSON that
        # belongs in the files -- a console rendering JSON means a file
        # formatter reached a stream handler.
        first = written.strip().splitlines()[0]
        assert not first.startswith("{"), f"console is rendering JSON: {first[:80]}"
