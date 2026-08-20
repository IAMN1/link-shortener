"""
A write that fails has to be visible to whoever asked for it.

``logging.Handler.handleError`` prints ``--- Logging error ---`` to stderr
and returns, so the standard library treats a failed write as nothing the
caller needs to know. Under a failover chain that is the wrong default: the
service decides to move work by catching exceptions from the call, so the
one failure it exists for -- a full disk, a volume that went away -- never
reaches it: three audit records lost, ``dropped_calls`` at zero,
``is_healthy()`` still ``True``, no switch.

Only this application's own records raise. The handlers sit on the root
logger, so they carry SQLAlchemy and werkzeug too, and neither has failover
behind it nor expects logging to throw.
"""

import io
import logging

import pytest

from link_shortener.infrastructure.failover.failover_service import (
    ALL_SERVICES_FAILED, FailoverService,
)
from link_shortener.infrastructure.logging.handlers.raising import (
    RaisingStreamHandler,
)


TAKEN_OVER = {}
"""Loggers this file has reconfigured, and how each one was found.

Filled by ``logger_writing_to`` at the moment it takes a logger over, not
written out by hand. A hand-written list is a second list beside the names
in the tests themselves, and the two parted company exactly as one would
expect: it named ``global``, ``audit`` and ``link_shortener.web`` while
``TestSomebodyElsesRecords`` was taking over ``sqlalchemy.engine``,
``werkzeug`` and ``celery`` as well. ``celery`` kept a handler whose
``write`` raises "No space left on device" for the rest of the session, and
``propagate=False`` with it -- so a later test that asked what a record from
``celery.worker`` looks like on disk found no record at all.
"""


@pytest.fixture(autouse=True)
def restore_the_loggers_this_file_takes_over():
    """
    Hand back every logger this file reconfigures.

    ``logging`` keeps named loggers for the life of the process, and
    ``logger_writing_to`` clears their handlers and installs a raising one.
    Left in place, that reaches whatever runs next -- and it did:
    ``pytest tests/unit tests/integration`` reddened
    ``test_a_record_from_another_library_is_stamped_too`` in
    ``tests/integration/infrastructure/test_records_reach_the_journals.py``
    with ``IndexError``, while the ordinary ``pytest tests/`` stayed green
    because the order happens to differ. A red that CI never sees is a red
    somebody looks for in their own change.
    """
    yield

    for name, (handlers, level, propagate) in TAKEN_OVER.items():
        log = logging.getLogger(name)
        log.handlers[:] = handlers
        log.setLevel(level)
        log.propagate = propagate
    TAKEN_OVER.clear()


class FullDisk(io.StringIO):
    """A stream that behaves like a volume with nothing left on it."""

    def write(self, text):
        raise OSError(28, "No space left on device")


def logger_writing_to(stream, name):
    """
    Build a logger with one raising handler over a given stream.

    Args:
        stream: Destination the handler writes to.
        name: Logger name, which decides whether failures raise.

    Returns:
        A configured ``logging.Logger``.
    """
    log = logging.getLogger(name)
    # Remembered before the first change and not after a later one, so a
    # logger taken over twice in one test is still given back as it was
    # found.
    TAKEN_OVER.setdefault(
        name, (log.handlers[:], log.level, log.propagate)
    )
    log.handlers.clear()
    log.setLevel(logging.INFO)
    log.propagate = False
    log.addHandler(RaisingStreamHandler(stream))
    return log


class TestOurOwnRecords:

    @pytest.mark.parametrize("name", ["global", "audit", "link_shortener.web"])
    def test_a_failed_write_reaches_the_caller(self, name):
        """Every name this application logs under."""
        log = logger_writing_to(FullDisk(), name)

        with pytest.raises(OSError) as caught:
            log.info("a record nobody will read")

        assert caught.value.errno == 28

    def test_a_write_that_works_stays_quiet(self):
        """The handler must not change the ordinary path."""
        stream = io.StringIO()
        log = logger_writing_to(stream, "global")

        log.info("written")

        assert "written" in stream.getvalue()


class TestSomebodyElsesRecords:

    @pytest.mark.parametrize("name", ["sqlalchemy.engine", "werkzeug", "celery"])
    def test_a_failed_write_is_swallowed_as_before(self, name, capsys):
        """Third-party code never agreed to have logging raise at it.

        It has no failover behind it either, so raising would turn a lost
        log line into a failed request.
        """
        log = logger_writing_to(FullDisk(), name)

        log.info("a record nobody will read")

        assert "--- Logging error ---" in capsys.readouterr().err


class TestWhatTheFailoverServiceNowSees:
    """The point of all of the above."""

    def test_a_full_disk_moves_the_work_and_counts_the_loss(self):
        written = []

        class Broken:
            def info(self, message):
                raise OSError(28, "No space left on device")

        class Working:
            def info(self, message):
                written.append(message)

        service = FailoverService(
            services=[(Broken(), "broken"), (Working(), "working")],
            check_interval=3600,
            health_checker=lambda service: True,
            logger=type("Quiet", (), {
                "warning": lambda self, *a, **k: None,
                "info": lambda self, *a, **k: None,
                "error": lambda self, *a, **k: None,
                "debug": lambda self, *a, **k: None,
            })(),
        )
        try:
            result = service.execute("info", "a record worth keeping")

            assert result is not ALL_SERVICES_FAILED
            assert written == ["a record worth keeping"]
            assert service.get_current_service_name() == "working"
        finally:
            service.shutdown()
