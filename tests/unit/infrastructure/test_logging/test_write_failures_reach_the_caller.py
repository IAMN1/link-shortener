"""
A write that fails has to be visible to whoever asked for it.

``logging.Handler.handleError`` prints ``--- Logging error ---`` to stderr
and returns, so the standard library treats a failed write as nothing the
caller needs to know. Under a failover chain that is the wrong default: the
service decides to move work by catching exceptions from the call, so the
one failure it exists for -- a full disk, a volume that went away -- never
reached it. Measured before the fix: three audit records lost,
``dropped_calls`` at zero, ``is_healthy()`` still ``True``, no switch.

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


LOGGERS_TAKEN_OVER = ("global", "audit", "link_shortener.web")
"""Names ``logger_writing_to`` reconfigures, and this file has to give back."""


@pytest.fixture(autouse=True)
def restore_the_loggers_this_file_takes_over():
    """
    Hand back every logger this file reconfigures.

    ``logging`` keeps named loggers for the life of the process, and
    ``logger_writing_to`` clears their handlers and installs a raising one.
    Left in place, that reaches whatever runs next. Measured: the suite is
    green only because ``tests/integration`` sorts before ``tests/unit`` --
    ``pytest tests/unit tests/integration`` fails
    ``test_the_named_logger_owns_no_handlers`` on what this file left on
    ``global``, and the ordinary ``pytest tests/`` never shows it.
    """
    saved = {
        name: (
            logging.getLogger(name).handlers[:],
            logging.getLogger(name).level,
            logging.getLogger(name).propagate,
        )
        for name in LOGGERS_TAKEN_OVER
    }

    yield

    for name, (handlers, level, propagate) in saved.items():
        log = logging.getLogger(name)
        log.handlers[:] = handlers
        log.setLevel(level)
        log.propagate = propagate


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
