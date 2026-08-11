"""
The logger production uses when only one implementation is available.

``_ModuleLogger`` is not a fallback nobody meets: with ``LOGGER_TYPE=null``,
with logging switched off, or whenever one of the two real implementations
fails to build, ``LoggerManager`` builds no failover and hands this out
instead. Nothing tested it, so it could be stripped of every request field
or made to lie about health with the suite still green.

The proxy beside it, ``FailoverLoggerProxy``, is covered in
``test_failover_proxies.py``; what is asserted here is the behaviour the two
must share, plus the one thing neither had: a bare ``exception(...)`` that
actually carries a traceback.
"""

from unittest.mock import Mock

import pytest

from link_shortener.infrastructure.logging.managers.logger_manager import (
    LoggerManager, _ModuleLogger,
)


@pytest.fixture
def underlying():
    """The single implementation the module logger writes through."""
    return Mock()


@pytest.fixture
def log(underlying):
    """A module logger for a named module."""
    return _ModuleLogger(underlying, "link_shortener.web.controllers")


class TestItIsWhatOneImplementationGetsYou:

    def test_the_manager_hands_it_out_when_there_is_no_failover(self):
        """The path this class exists for, asserted through the manager."""
        manager = LoggerManager(logger_type="null")

        assert manager._failover_service is None
        assert isinstance(manager.get_logger("some.module"), _ModuleLogger)


class TestTheModuleNameTravelsWithEveryRecord:

    @pytest.mark.parametrize(
        "level", ["debug", "info", "warning", "error"]
    )
    def test_every_level_carries_it(self, log, underlying, level):
        """Dropping it from one level is the shape of loss to expect.

        Without the module name a line cannot be traced back to the code
        that wrote it, which is the only thing this wrapper adds.
        """
        getattr(log, level)("a message", extra="value")

        call = getattr(underlying, level).call_args
        assert call.args == ("a message",)
        assert call.kwargs["module"] == "link_shortener.web.controllers"
        assert call.kwargs["extra"] == "value"

    def test_exception_carries_it_too(self, log, underlying):
        log.exception("it broke")

        assert underlying.exception.call_args.kwargs["module"] == (
            "link_shortener.web.controllers"
        )


class TestBoundFields:

    def test_bind_returns_a_new_logger_and_leaves_the_old_one_alone(
        self, log, underlying
    ):
        """Binding on a shared logger must not reach its other users."""
        bound = log.bind(request_id="req-1")

        bound.info("with context")
        log.info("without context")

        assert isinstance(bound, _ModuleLogger)
        assert bound is not log
        first, second = underlying.info.call_args_list
        assert first.kwargs["request_id"] == "req-1"
        assert "request_id" not in second.kwargs

    def test_binding_twice_keeps_both_fields(self, log, underlying):
        log.bind(request_id="req-1").bind(user_id="u-2").info("both")

        kwargs = underlying.info.call_args.kwargs
        assert kwargs["request_id"] == "req-1"
        assert kwargs["user_id"] == "u-2"

    def test_a_call_field_wins_over_a_bound_one(self, log, underlying):
        """The rule the failover proxy follows, stated here as well."""
        log.bind(request_id="bound").info("said", request_id="from the call")

        assert underlying.info.call_args.kwargs["request_id"] == "from the call"


class TestHealth:

    def test_it_reports_what_the_implementation_reports(self, underlying):
        """Answering ``True`` regardless would hide a dead logger.

        Both answers are asserted: a proxy hard-wired to either one passes
        a test that only ever checks the other.
        """
        log = _ModuleLogger(underlying, "m")

        underlying.is_healthy.return_value = True
        assert log.is_healthy() is True

        underlying.is_healthy.return_value = False
        assert log.is_healthy() is False


class TestABareExceptionCallCarriesATraceback:
    """``exc_info`` defaulted to ``None``, and a falsy value renders none.

    So ``log.exception("...")`` written the ordinary way -- the way
    ``logging`` and ``structlog`` both accept -- produced a line that reads
    like a traceback and has none. Every call in ``src/`` passes
    ``exc_info`` explicitly today, which is why nothing noticed.
    """

    def test_the_default_asks_for_the_exception_being_handled(
        self, log, underlying
    ):
        try:
            raise ValueError("boom")
        except ValueError:
            log.exception("it broke")

        assert underlying.exception.call_args.kwargs["exc_info"] is True

    def test_an_explicit_exception_is_passed_through(self, log, underlying):
        error = ValueError("boom")

        log.exception("it broke", exc_info=error)

        assert underlying.exception.call_args.kwargs["exc_info"] is error

    def test_none_still_means_no_traceback(self, log, underlying):
        """The old default stays available for a caller who wants it."""
        log.exception("just the line", exc_info=None)

        assert underlying.exception.call_args.kwargs["exc_info"] is None
