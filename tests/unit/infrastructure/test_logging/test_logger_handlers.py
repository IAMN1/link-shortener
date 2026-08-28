"""Tests for the ``Logger`` adapters.

These sit between the application and whichever logging library is in use.
What matters is that context survives binding, that the adapters agree with
each other, and that a health check reports the truth -- the failover
service switches implementations based on it.
"""

import logging

import pytest

from link_shortener.infrastructure.logging.handlers.logger.null_logger import (
    NullLogger,
)
from link_shortener.infrastructure.logging.handlers.logger.standard import (
    StandardLogger,
)
from link_shortener.infrastructure.logging.handlers.logger.structlog import (
    StructLogger,
)


@pytest.fixture
def captured(caplog):
    """Capture records emitted through the standard library."""
    caplog.set_level(logging.DEBUG)
    return caplog


class TestStandardLogger:
    """Adapter over ``logging.Logger``."""

    def test_message_reaches_the_log(self, captured):
        StandardLogger("test.standard").info("hello")

        assert captured.records[-1].getMessage() == "hello"

    @pytest.mark.parametrize(
        "level, expected",
        [
            ("debug", logging.DEBUG),
            ("info", logging.INFO),
            ("warning", logging.WARNING),
            ("error", logging.ERROR),
        ],
    )
    def test_each_level_maps_through(self, captured, level, expected):
        """A level that silently downgrades would hide errors."""
        getattr(StandardLogger("test.levels"), level)("msg")

        assert captured.records[-1].levelno == expected

    def test_fields_are_attached_to_the_record(self, captured):
        StandardLogger("test.fields").info("msg", request_id="req-1", clicks=2)

        record = captured.records[-1]
        assert record.request_id == "req-1"
        assert record.clicks == 2

    def test_bind_returns_a_new_logger_and_keeps_the_name(self):
        """Binding must not mutate the logger it was called on.

        A mutating bind would leak one request's context into the next,
        which is the failure mode that makes a shared logger dangerous.
        """
        base = StandardLogger("test.bind")
        bound = base.bind(request_id="req-1")

        assert bound is not base
        assert base._bound_fields == {}
        assert bound._bound_fields == {"request_id": "req-1"}
        assert bound._logger.name == "test.bind"

    def test_bound_fields_appear_on_every_call(self, captured):
        StandardLogger("test.bound").bind(request_id="req-1").info("msg")

        assert captured.records[-1].request_id == "req-1"

    def test_binding_accumulates(self, captured):
        (
            StandardLogger("test.acc")
            .bind(request_id="req-1")
            .bind(user_id="u-2")
            .info("msg")
        )

        record = captured.records[-1]
        assert record.request_id == "req-1"
        assert record.user_id == "u-2"

    def test_call_field_overrides_a_bound_one(self, captured):
        """The nearer value wins, which is the usual expectation."""
        StandardLogger("test.override").bind(stage="early").info(
            "msg", stage="late"
        )

        assert captured.records[-1].stage == "late"

    def test_module_field_is_renamed_to_avoid_a_collision(self, captured):
        """``module`` is a LogRecord attribute; passing it through raised.

        The rename is what lets application code use the obvious field name
        without ``logging`` refusing the record outright.
        """
        StandardLogger("test.module").info("msg", module="web.api")

        record = captured.records[-1]
        assert record.module_name == "web.api"
        assert record.module != "web.api"

    def test_exception_records_the_traceback(self, captured):
        try:
            raise ValueError("boom")
        except ValueError:
            StandardLogger("test.exc").exception("failed")

        record = captured.records[-1]
        assert record.levelno == logging.ERROR
        assert record.exc_info is not None

    def test_exception_accepts_an_explicit_error(self, captured):
        """Logging an error caught elsewhere must still carry it."""
        error = ValueError("explicit")

        StandardLogger("test.exc2").exception("failed", exc_info=error)

        assert captured.records[-1].exc_info is not None

    def test_unhealthy_when_no_handler_can_be_reached(self):
        """Nothing to write to means nothing is written -- not healthy.

        The failover service reads this to decide whether to hand the work
        down, so a logger that reports health while discarding everything
        would keep the fallback from ever engaging.
        """
        logger = StandardLogger("test.health.none")
        logger._logger.handlers = []
        # Cut off from the root's handlers too: the question is whether a
        # record reaches anything, not whether this logger owns the thing
        # it reaches.
        logger._logger.propagate = False
        try:
            assert logger.is_healthy() is False
        finally:
            logger._logger.propagate = True

    def test_healthy_when_only_the_root_carries_the_handlers(self):
        """How this application is actually wired.

        ``bootstrap.setup_logging`` puts the handlers on the root logger
        and lets every named logger propagate to it, so `handlers` on a
        logger built by ``LoggerManager`` is empty and always was. Read that
        way the standard logger called itself unwell for its entire life
        while its records arrived -- and the background check now hands the
        work down on that answer, which took the work off a logger that was
        working and could never give it back.
        """
        root = logging.getLogger()
        saved = root.handlers[:]
        root.handlers = [logging.NullHandler()]
        logger = StandardLogger("test.health.rootonly")
        logger._logger.handlers = []
        try:
            assert logger._logger.handlers == []
            assert logger.is_healthy() is True
        finally:
            root.handlers = saved

    def test_healthy_with_a_handler(self):
        logger = StandardLogger("test.health.some")
        logger._logger.addHandler(logging.NullHandler())
        try:
            assert logger.is_healthy() is True
        finally:
            logger._logger.handlers = []

    def test_health_check_leaves_no_handlers_behind(self):
        """The probe builds a temporary logger; it must clean it up."""
        logger = StandardLogger("test.health.leak")
        logger._logger.addHandler(logging.NullHandler())
        try:
            logger.is_healthy()
            probe = logging.getLogger("test.health.leak._health_test")
            assert probe.handlers == []
        finally:
            logger._logger.handlers = []


class TestStructLogger:
    """Adapter over structlog."""

    def test_bind_returns_a_new_logger(self):
        base = StructLogger("test.struct")
        bound = base.bind(request_id="req-1")

        assert bound is not base
        assert isinstance(bound, StructLogger)

    def test_logging_does_not_raise(self):
        """The adapter must not add failure modes of its own."""
        logger = StructLogger("test.struct.calls")

        logger.debug("d")
        logger.info("i", field=1)
        logger.warning("w")
        logger.error("e")

    def test_exception_does_not_raise_outside_a_handler(self):
        """Called with an explicit error and no active exception."""
        StructLogger("test.struct.exc").exception(
            "failed", exc_info=ValueError("boom")
        )

    def test_reports_healthy(self):
        assert StructLogger("test.struct.health").is_healthy() is True

    def test_reports_unhealthy_when_the_backend_fails(self):
        """Health has to reflect the backend, not just return True."""
        logger = StructLogger("test.struct.broken")

        class Broken:
            def debug(self, *a, **k):
                raise RuntimeError("backend down")

        logger._logger = Broken()

        assert logger.is_healthy() is False


class TestNullLogger:
    """The do-nothing implementation used when logging is off."""

    def test_every_call_is_silent(self, captured):
        logger = NullLogger()

        logger.debug("d")
        logger.info("i")
        logger.warning("w")
        logger.error("e")
        logger.exception("x", exc_info=ValueError("boom"))

        assert captured.records == []

    def test_reports_healthy(self):
        """Discarding on purpose is a working state, not a failure."""
        assert NullLogger().is_healthy() is True
