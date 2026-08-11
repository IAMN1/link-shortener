import logging
import logging.handlers


OWN_LOGGER_NAMES = ("link_shortener", "audit", "global")
"""Roots of the logger names this application writes under.

``global`` is what ``StandardLogger`` and ``StructLogger`` are built with,
``audit`` is the audit tree, and ``link_shortener`` covers module loggers.
Everything else -- ``sqlalchemy.engine``, ``werkzeug``, ``celery`` -- keeps
the standard library's behaviour.
"""


def _is_own(record: logging.LogRecord) -> bool:
    """
    Say whether a record was written by this application.

    Args:
        record: The record whose write failed.

    Returns:
        ``True`` when the record's logger belongs to this application.
    """
    return record.name.split(".")[0] in OWN_LOGGER_NAMES


class _RaisesForOwnRecords:
    """
    Let a failed write reach the caller instead of dying on stderr.

    ``logging.Handler.handleError`` swallows the failure: with
    ``logging.raiseExceptions`` true -- the default -- it prints to
    stderr and returns, and with it false the exception "gets silently
    ignored" (``logging`` docs). Either way it is invisible to whoever
    asked for the write. That is the right default for a library, and the
    wrong one here: the whole point of ``FailoverService`` is to move work
    off an implementation that cannot write, and it decides by catching
    exceptions from the call. Measured before this existed -- a stream
    whose ``write`` raises ``OSError(ENOSPC)``, which is a full disk or a
    volume that went away:
    three audit records were lost, ``dropped_calls`` stayed at zero,
    ``is_healthy()`` answered ``True`` and no switch happened. What did
    appear was 5457 bytes of ``--- Logging error ---`` on stderr, written
    by the standard library and counted by nothing.

    Only this application's own records are raised for. The handlers sit
    on the root logger, so they also carry SQLAlchemy, werkzeug and celery
    -- code that never agreed to have logging raise at it, and that has no
    failover behind it either.
    """

    def handleError(self, record: logging.LogRecord) -> None:
        """
        Re-raise the write failure, or fall back to the default.

        Called from inside the ``except`` clause of ``emit``, so a bare
        ``raise`` re-raises the exception that is being handled.

        Args:
            record: The record whose write failed.
        """
        if _is_own(record):
            raise

        super().handleError(record)


class RaisingStreamHandler(_RaisesForOwnRecords, logging.StreamHandler):
    """A console handler whose failures are not silent."""


class RaisingWatchedFileHandler(
    _RaisesForOwnRecords, logging.handlers.WatchedFileHandler
):
    """A file handler whose failures are not silent."""
