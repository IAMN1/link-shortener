import logging
import logging.handlers
import os
from typing import List, Optional, Tuple

import structlog

from link_shortener.application.ports.journal_reader import Journal
from link_shortener.application.ports.logging_status import JournalUnavailable
from link_shortener.infrastructure.failover.minimal_logger import MinimalLogger
from link_shortener.infrastructure.logging.handlers.raising import (
    RaisingStreamHandler, RaisingWatchedFileHandler
)
from link_shortener.infrastructure.logging.structlog_config import configure_structlog
from link_shortener.infrastructure.logging.logging_settings import LoggingSettings
from link_shortener.infrastructure.logging.formatters.console_formatter import ConsoleFormatter
from link_shortener.infrastructure.logging.formatters.json_formatter import JSONFormatter
from link_shortener.infrastructure.logging.utils import UTC_SECONDS


FOREIGN_PRE_CHAIN: list = [
    structlog.stdlib.add_log_level,
    structlog.stdlib.add_logger_name,
    structlog.processors.TimeStamper(fmt=UTC_SECONDS, utc=True),
]
"""What a record gets when it was not made through structlog.

``ProcessorFormatter`` runs the application's chain only for records that
came from structlog. Everything else -- Celery's own logger, werkzeug's,
any library's -- goes straight to the renderer with whatever the standard
``LogRecord`` carries, which is neither a timestamp field nor a level one.
Measured on the live stack: 14 lines of 45 in `application.log` had no
``timestamp`` and no ``level`` at all, a third of the file, and among them
were the two Celery writes per redirect -- ``Task received`` and ``Task
succeeded`` -- so the share grows with traffic rather than being a start-up
artefact.

Those are the lines a reader most wants when something is wrong, and they
were the ones no filter by time or level could reach. This chain gives
them the same three fields the application's own records carry, from the
same constant, so one journal has one shape.
"""


_STDERR = MinimalLogger()
"""Where a failure to build the journals is said, having no journal to say it in.

The same stream and the same shape ``FailoverService`` reports itself
through, and for the same reason: these are the lines around a logging
failure, and they are read beside the journal's own.
"""


_UNAVAILABLE: List[JournalUnavailable] = []
"""Journals this process could not open, in the order they were tried.

Kept in the module that opens them, and read from it, rather than handed
to whoever builds the container: this is a fact about *this* process --
its file descriptors, its user, its mount -- exactly as the worker id
beside it in ``LoggingStatus`` is. A container built without
``setup_logging``, and there are several in the tests, would otherwise
answer "every journal opened" about journals it never opened.
"""


_OPENED: List[str] = []
"""Journals this process opened, in the order they were built.

Kept beside the failures because the failures alone cannot be read: an
empty list of them is the answer both for a process writing all three
journals and for one writing none, and ``LOG_TO_FILE=false`` is a
documented way to be the second. Reporting only failures would put
"every journal is fine" on the screen of a deployment with no journals
-- the same sentence ``cache_configured`` was added to stop the health
answer saying about Redis.
"""


def journals_written() -> Tuple[str, ...]:
    """
    Which journals this process opened when logging was set up.

    About the files as they were at start-up. A journal that opened and
    was broken afterwards is still named here -- the handler exists, and
    what its chain has found since is the failover service's answer, not
    this one's.

    Returns:
        One name per journal opened, empty where none were -- which is a
        configuration and not a fault.
    """
    return tuple(_OPENED)


def journals_unavailable() -> Tuple[JournalUnavailable, ...]:
    """
    Which journals this process failed to open when logging was set up.

    Returns:
        One entry per journal that could not be opened, empty when every
        configured journal was.
    """
    return tuple(_UNAVAILABLE)


def _journal_missing(journal: Journal) -> bool:
    """
    Whether a journal was asked for in this process and could not be opened.

    Args:
        journal: Which journal to ask about.

    Returns:
        True if its handler could not be built.
    """
    return any(entry.journal == journal.value for entry in _UNAVAILABLE)


def _stream_handler_class(settings: LoggingSettings) -> type:
    """
    The console handler this process writes through.

    Args:
        settings: LoggingSettings object.

    Returns:
        The raising handler, or the standard library's own.
    """
    if settings.raise_on_write_failure:
        return RaisingStreamHandler

    return logging.StreamHandler


def _file_handler_class(settings: LoggingSettings) -> type:
    """
    The file handler this process writes through.

    Watched either way -- rotation is done from outside and the file has to
    be followed whoever is writing. What the setting decides is only
    whether a failed write reaches the caller.

    Args:
        settings: LoggingSettings object.

    Returns:
        The raising handler, or the standard library's own.
    """
    if settings.raise_on_write_failure:
        return RaisingWatchedFileHandler

    return logging.handlers.WatchedFileHandler


def _console_formatter(settings: LoggingSettings) -> logging.Formatter:
    """
    How a record is dressed for a person reading a terminal.

    Args:
        settings: LoggingSettings object.

    Returns:
        A plain text formatter for the ``standard`` logger type, and a
        structlog one -- coloured -- for the others.

    Note:
        Returned by the base type both branches produce: one builds a
        ``ConsoleFormatter`` and the other a ``ProcessorFormatter``, and a
        variable typed from whichever came first rejects the other.
    """
    if settings.logger_type == "standard":
        # `LOG_DATE_FORMAT` reaches the line it was always documented to
        # dress. `ConsoleFormatter` takes a `datefmt` and stamps with it,
        # and was built here with none, so the setting was read from the
        # environment, carried on `LoggingSettings` and consulted by
        # nothing -- whatever a deployment set, the console kept the
        # formatter's own default. The journals are unaffected: they are
        # stamped by `UTC_SECONDS`, which is not a setting, so a format
        # written for a person cannot make a file unreadable by a program.
        return ConsoleFormatter(datefmt=settings.log_date_format)

    return structlog.stdlib.ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer(colors=True),
        foreign_pre_chain=FOREIGN_PRE_CHAIN,
    )


def _file_formatter(settings: LoggingSettings) -> logging.Formatter:
    """
    How a record is dressed for a journal a program will read back.

    JSON either way, so that one journal has one shape whichever logger
    type a deployment chose -- which is what ``FileJournalReader`` parses
    and what every filter in the admin surfaces matches on.

    Args:
        settings: LoggingSettings object.

    Returns:
        A ``JSONFormatter`` for the ``standard`` logger type, and a
        structlog ``ProcessorFormatter`` rendering JSON for the others.
    """
    if settings.logger_type == "standard":
        return JSONFormatter()

    return structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=FOREIGN_PRE_CHAIN,
    )


def _console_handler(settings: LoggingSettings, level: int) -> logging.Handler:
    """
    Build a handler writing to the console at one level.

    Args:
        settings: LoggingSettings object.
        level: Lowest level this handler passes on.

    Returns:
        The configured handler, attached to nothing yet.
    """
    handler = _stream_handler_class(settings)()
    handler.setLevel(level)
    handler.setFormatter(_console_formatter(settings))
    return handler


def _open_journal(
    settings: LoggingSettings,
    journal: Journal,
    path: str,
    level: int,
) -> Optional[logging.Handler]:
    """
    Build the handler for one journal, or record why there is none.

    A file handler opens its file while it is being built, so a path that
    will not open -- a directory in a file's place, a mode this user
    cannot write, a full disk -- raised out of here, out of
    ``setup_logging`` and out of ``create_app`` with it. Measured on the
    live stack with ``application.log`` replaced by a directory: the
    container sat in ``Restarting (1)``, the public ``/health`` answered
    ``000``, and ``flask maintenance health`` -- the command an operator
    runs at exactly that moment -- ended in an ``IsADirectoryError``
    traceback instead of a table.

    That is the failure the whole failover exists to survive, arriving
    one step before failover can see it, and ``dockers/logrotate.conf``
    promises the opposite in as many words: "a file the application
    cannot write to: the write fails, `FailoverService` counts it in
    `dropped_calls`". So the journal that will not open is left out and
    named in ``journals_unavailable``, and the process keeps the journals
    that did open.

    ``OSError`` and not every exception: it is the family the file system
    answers with, and a wider net here would swallow a mistake in the
    formatter above it and leave a deployment quietly without a journal
    for a reason that is nobody's operating system.

    Args:
        settings: LoggingSettings object.
        journal: Which journal this is, named as ``Journal`` names it.
        path: Full path to the file.
        level: Lowest level this handler passes on.

    Returns:
        The configured handler, or ``None`` if the file could not be
        opened.
    """
    try:
        os.makedirs(settings.log_dir, exist_ok=True)
        handler = _file_handler_class(settings)(path, encoding="utf-8")
    except OSError as error:
        _UNAVAILABLE.append(JournalUnavailable(journal.value, str(error)))
        _STDERR.error(
            f"Journal '{journal.value}' cannot be opened and will not be "
            f"written by this process: {error}"
        )
        return None

    _OPENED.append(journal.value)
    handler.setLevel(level)
    handler.setFormatter(_file_formatter(settings))
    return handler


def _ensure_a_place_to_write(
    settings: LoggingSettings,
    logger: logging.Logger,
    level: int,
    *journals: Journal,
) -> None:
    """
    Leave no logger without a handler, whichever way it got there.

    A logger with no handlers at all is not silent: the standard library
    answers those records with ``lastResort`` -- level ``WARNING``, to
    stderr, formatted by nothing, whatever ``LOGGER_TYPE`` asked for --
    and drops everything below without a word. Measured with
    ``LOG_TO_CONSOLE=false`` and ``LOG_TO_FILE=false``: an ``error``
    record arrived on stderr as the bare line ``an error nobody asked to
    see``, on a deployment that had switched both destinations off.

    Which handler depends on how the logger came to be empty, and the two
    cases are opposite:

    * Its journal would not open. Something failed, and the records were
      meant to be kept, so they go to the console -- see ``_open_journal``.
      Only where its own journal is what failed: a deployment that
      switched the console off and keeps its files does not get one back.
    * Nothing failed and nothing was asked for. ``LOG_TO_CONSOLE=false``
      with ``LOG_TO_FILE=false`` is a deployment asking for no output, and
      it gets exactly that -- a ``NullHandler``, which is what the
      ``LOGGING_ENABLED=false`` branch installs for the same reason.

    Args:
        settings: LoggingSettings object.
        logger: The logger to give a handler to.
        level: Lowest level a console handler would pass on.
        *journals: The journals this logger was to be written to.
    """
    if logger.handlers:
        return

    if any(_journal_missing(journal) for journal in journals):
        logger.addHandler(_console_handler(settings, level))
        return

    logger.addHandler(logging.NullHandler())


def _setup_console_handler(settings: LoggingSettings, root_logger: logging.Logger):
    """
    Add a console handler to the root logger.

    For the 'standard' logger type, a plain text ConsoleFormatter is used.
    For other types (structlog), a structlog ProcessorFormatter with ConsoleRenderer is used,
    which produces coloured output when debug is enabled.

    Args:
        settings: LoggingSettings object.
        root_logger: Root logger instance.
    """
    if not settings.log_to_console:
        return

    root_logger.addHandler(
        _console_handler(settings, settings.get_log_level_int())
    )


def _setup_file_handler(settings: LoggingSettings, root_logger: logging.Logger):
    """
    Add a file handler for general application logs.

    The log file is watched for external rotation (WatchedFileHandler),
    and a file that will not open leaves the root logger without it
    rather than ending the process -- see ``_open_journal``.

    Args:
        settings: LoggingSettings object.
        root_logger: Root logger instance.
    """
    if not settings.should_log_to_file:
        return

    handler = _open_journal(
        settings,
        Journal.APPLICATION,
        settings.log_file_path,
        settings.get_log_level_int(),
    )

    if handler is not None:
        root_logger.addHandler(handler)


def _setup_audit_handler(settings: LoggingSettings):
    """
    Configure a dedicated logger for audit events.

    Audit logs are written to a separate file (audit.log) and optionally to the console.
    The same formatting logic (plain text or structlog) is applied based on logger_type.

    Args:
        settings: LoggingSettings object.
    """
    if not settings.audit_enabled:
        return

    audit_logger = logging.getLogger("audit")
    audit_logger.handlers.clear()
    audit_logger.propagate = False
    audit_logger.setLevel(logging.INFO)

    if settings.log_to_console:
        # The same date format on the audit chain's console, for the same
        # reason: one deployment, one console, one clock on it.
        audit_logger.addHandler(_console_handler(settings, logging.INFO))

    if settings.should_log_to_file:
        audit_file = os.path.join(settings.log_dir, f"{settings.audit_log_filename}.log")

        handler = _open_journal(settings, Journal.AUDIT, audit_file, logging.INFO)

        if handler is not None:
            audit_logger.addHandler(handler)

    _ensure_a_place_to_write(settings, audit_logger, logging.INFO, Journal.AUDIT)


def _setup_error_handler(settings: LoggingSettings, root_logger: logging.Logger):
    """
    Add a file handler that captures only ERROR and above messages.

    Error logs are written to a separate file (error.log) in the same format
    as general application logs (JSON or structured text).

    Args:
        settings: LoggingSettings object.
        root_logger: Root logger instance.
    """
    if not settings.log_to_file:
        return

    error_file = os.path.join(settings.log_dir, f"{settings.error_log_filename}.log")

    handler = _open_journal(settings, Journal.ERROR, error_file, logging.ERROR)

    if handler is not None:
        root_logger.addHandler(handler)


def setup_logging(settings: LoggingSettings) -> None:
    """
    Main entry point for logging configuration.

    Configures structlog, sets up handlers on the root logger, and configures
    the audit logger. If logging is disabled, a ``NullHandler`` is attached and
    third-party loggers are silenced.

    A journal whose file cannot be opened is left out rather than allowed
    to end the process; what was left out is readable afterwards through
    ``journals_unavailable`` and reported by ``/api/v1/admin/health``.

    Every switch comes off ``settings``. Two of them used to arrive as
    arguments beside it while ``audit_enabled`` also sat *on* it, so the
    audit chain was told twice whether to exist. Measured with the two
    disagreeing -- ``settings.audit_enabled`` false, the argument true --
    the audit logger came out of here with no handlers and its
    ``propagate`` untouched, so every audit record went up to the root
    and was written into ``application.log``: the trail kept, in the
    wrong file, saying nothing about it. Both callers read both names
    from one configuration, which is why nothing had gone wrong yet.

    Args:
        settings: ``LoggingSettings`` object with all configuration parameters.
    """
    logging_enabled = settings.logging_enabled
    audit_enabled = settings.audit_enabled

    # This process is being configured from the beginning, so what an
    # earlier configuration of it opened, or could not open, says nothing
    # about what this one does. Cleared here rather than appended to for
    # the same reason the root logger's handlers are.
    _UNAVAILABLE.clear()
    _OPENED.clear()

    # Always configure structlog – it may still be used by other parts (e.g., audit)
    configure_structlog(settings)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    if logging_enabled:
        root_logger.setLevel(settings.get_log_level_int())
        _setup_console_handler(settings, root_logger)
        _setup_file_handler(settings, root_logger)
        _setup_error_handler(settings, root_logger)
        _ensure_a_place_to_write(
            settings,
            root_logger,
            settings.get_log_level_int(),
            Journal.APPLICATION,
            Journal.ERROR,
        )
    else:
        root_logger.setLevel(logging.CRITICAL)
        root_logger.addHandler(logging.NullHandler())

    # Configure audit logger
    if audit_enabled:
        _setup_audit_handler(settings)
    else:
        audit_logger = logging.getLogger("audit")
        audit_logger.handlers.clear()
        # Switched off means written nowhere, not written elsewhere. A
        # `NullHandler` does not stop a record travelling: with
        # `propagate` left true the record goes on up to the root and
        # lands in `application.log`, so a deployment that turned the
        # audit trail off would find it in the other journal, unmarked
        # and unrotated as an audit file. Measured with
        # `AUDIT_ENABLED=false`: an `audit` record reached
        # `application.log` while `audit.log` was never created. Nothing
        # writes through this logger on that setting today -- the DI
        # component hands out a null audit logger -- which is what kept
        # it from being noticed rather than what makes it safe. The
        # branch above sets the same flag for the same reason.
        audit_logger.propagate = False
        audit_logger.addHandler(logging.NullHandler())

    # Set the levels for third-party libraries (default CRITICAL if logging is off)
    sqlalchemy_level = logging.CRITICAL
    werkzeug_level = logging.CRITICAL

    if logging_enabled:
        sqlalchemy_level = getattr(logging, settings.sqlalchemy_log_level.upper(), logging.WARNING)
        logging.getLogger("sqlalchemy.engine").setLevel(sqlalchemy_level)

        werkzeug_level = getattr(logging, settings.werkzeug_log_level.upper(), logging.WARNING)
        logging.getLogger("werkzeug").setLevel(werkzeug_level)
    else:
        logging.getLogger("sqlalchemy.engine").setLevel(logging.CRITICAL)
        logging.getLogger("werkzeug").setLevel(logging.CRITICAL)


    # Log that logging has been initialized (using extra fields to carry configuration)
    root_logger.info(
        "Logging has been initialized.",
        extra={
            "debug_mode": settings.debug,
            "log_level": settings.log_level_str,
            "log_to_console": settings.log_to_console,
            "log_to_file": settings.log_to_file,
            "log_dir": settings.log_dir if settings.log_to_file else None,
            "sqlalchemy_log_level": sqlalchemy_level,
            "werkzeug_log_level": werkzeug_level
        }
    )

    # Said through the journals that did open, once they are open, and at
    # a level that reaches `error.log` if that is one of them. The stderr
    # line from `_open_journal` is written before there is anywhere else
    # to write it; this one is for the reader who has the files.
    for entry in _UNAVAILABLE:
        root_logger.error(
            "Journal is unavailable in this process.",
            extra={"journal": entry.journal, "reason": entry.reason},
        )
