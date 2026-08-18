"""
The two proxies that stand between the application and the failover service.

Nothing reached them when this file was written. Every logging and audit
call the application makes goes through one of these, and the whole suite
passed with their bodies emptied: a proxy that never calls ``execute`` at
all leaves the application silent -- no logs, no audit trail -- and every
other test green. (Two tests in
``test_managers_wire_the_failover_service`` now fail on that same
emptying, because they follow a manager's own logger down into the chain;
what is below is still the only thing holding the proxies themselves.)

They are thin on purpose, which is exactly why nobody wrote a test for
them, and exactly why the ways they can go wrong are quiet ones: forwarding
under the wrong method name, losing the bound fields, or reading the
failover service's answer with the wrong comparison so a dead logging stack
reports itself healthy.
"""

import pytest

from link_shortener.application.ports.logger.audit import AuditEvent
from link_shortener.infrastructure.failover.failover_service import (
    ALL_SERVICES_FAILED,
)
from link_shortener.infrastructure.logging.managers.audit_manager import (
    FailoverAuditLoggerProxy,
)
from link_shortener.infrastructure.logging.managers.logger_manager import (
    FailoverLoggerProxy,
)


class RecordingService:
    """
    Stands in for ``FailoverService`` and remembers what it was asked.

    Attributes:
        calls: Every ``execute`` call, as ``(method_name, args, kwargs)``.
        answer: What ``execute`` returns.
    """

    def __init__(self, answer=None):
        self.calls = []
        self.answer = answer

    def execute(self, method_name, *args, **kwargs):
        """Record the call and answer whatever the test asked for."""
        self.calls.append((method_name, args, kwargs))
        return self.answer


class TestTheLoggerProxyForwards:
    """Every log call has to reach the failover service."""

    @pytest.mark.parametrize(
        "level", ["debug", "info", "warning", "error", "exception"]
    )
    def test_each_level_reaches_the_service_under_its_own_name(self, level):
        """
        The name is what picks the method on the real logger.

        Forwarding "info" for a call to ``error`` costs the level, not the
        line, so nothing looks broken until somebody greps for errors.

        Args:
            level: The logging method being exercised.
        """
        service = RecordingService()
        proxy = FailoverLoggerProxy(service, "web.api")

        getattr(proxy, level)("something happened")

        assert len(service.calls) == 1
        name, args, kwargs = service.calls[0]
        assert name == level
        assert args == ("something happened",)
        assert kwargs["module"] == "web.api"

    def test_the_module_name_travels_with_the_call(self):
        """Without it every line reads as coming from the same place."""
        service = RecordingService()
        proxy = FailoverLoggerProxy(service, "web.api")

        proxy.info("hello")

        _, _, kwargs = service.calls[0]
        assert kwargs["module"] == "web.api"

    def test_the_module_name_cannot_be_overridden_by_the_caller(self):
        """
        It says where the line came from, so the caller may not rewrite it.

        Merging the caller's kwargs last lets any `module=` argument win,
        and lines start attributing themselves to whatever the caller felt
        like naming.
        """
        service = RecordingService()
        proxy = FailoverLoggerProxy(service, "web.api")

        proxy.info("hello", module="somewhere.else")

        _, _, kwargs = service.calls[0]
        assert kwargs["module"] == "web.api"

    def test_exception_carries_the_traceback(self):
        """
        `exc_info` is the one thing `exception` adds over `error`.

        Dropping it leaves a line that still says what happened and no
        longer says where.
        """
        service = RecordingService()
        proxy = FailoverLoggerProxy(service, "web.api")
        error = ValueError("boom")

        proxy.exception("it broke", exc_info=error)

        _, _, kwargs = service.calls[0]
        assert kwargs["exc_info"] is error

    def test_a_later_binding_wins_over_an_earlier_one(self):
        """
        Rebinding a field has to replace it, not be ignored.

        Merging the other way round -- old over new -- keeps the first
        value forever, so a proxy rebound for a second request goes on
        stamping the first request's id.
        """
        service = RecordingService()
        proxy = FailoverLoggerProxy(service, "web.api").bind(request_id="r-1")

        proxy.bind(request_id="r-2").info("hello")

        _, _, kwargs = service.calls[0]
        assert kwargs["request_id"] == "r-2"

    def test_a_call_field_wins_over_a_bound_field_of_the_same_name(self):
        """
        The same merge order as the audit proxy keeps, on this one.

        A field bound for the request is context; one passed at the call
        is what this line is about. Merging the bound fields last would
        make every line report the context's value under a name the caller
        had just set.
        """
        service = RecordingService()
        proxy = FailoverLoggerProxy(service, "web.api").bind(status="bound")

        proxy.info("hello", status="from the call")

        _, _, kwargs = service.calls[0]
        assert kwargs["status"] == "from the call"

    def test_the_answer_of_the_failover_service_is_passed_back_up(self):
        """
        `_call` returns it, and that is how exhaustion could ever be seen.

        The level methods discard it today; a `_call` that returns nothing
        makes the distinction unreachable for anyone who later looks.
        """
        service = RecordingService(ALL_SERVICES_FAILED)
        proxy = FailoverLoggerProxy(service, "web.api")

        assert proxy._call("info", "hello") is ALL_SERVICES_FAILED

    def test_bound_fields_travel_with_the_call(self):
        """
        Binding is how the request id gets onto every line of a request.

        A proxy that dropped them would still log, and every line would
        stop being attributable to a request.
        """
        service = RecordingService()
        proxy = FailoverLoggerProxy(service, "web.api").bind(request_id="r-1")

        proxy.warning("careful", extra_field="x")

        _, _, kwargs = service.calls[0]
        assert kwargs["request_id"] == "r-1"
        assert kwargs["extra_field"] == "x"

    def test_a_second_binding_keeps_the_first_ones_fields(self):
        """
        Binding twice must add, not replace the whole set.

        A `bind` that starts from the new fields alone drops the request
        id the moment anything binds a second field to the same proxy.
        """
        service = RecordingService()
        proxy = FailoverLoggerProxy(service, "web.api").bind(request_id="r-1")

        proxy.bind(user_id="u-1").info("hello")

        _, _, kwargs = service.calls[0]
        assert kwargs["request_id"] == "r-1"
        assert kwargs["user_id"] == "u-1"

    def test_binding_does_not_change_the_proxy_it_came_from(self):
        """Otherwise one request's fields leak into the next one's lines."""
        service = RecordingService()
        original = FailoverLoggerProxy(service, "web.api")

        bound = original.bind(request_id="r-1")
        original.info("plain")

        assert bound is not original
        _, _, kwargs = service.calls[0]
        assert "request_id" not in kwargs

    def test_health_is_true_only_when_the_service_answers_true(self):
        """
        A dead logging stack must not report itself healthy.

        `is True` and not `is not None`: exhaustion answers
        ALL_SERVICES_FAILED, which is truthy and is not None, so the looser
        comparison calls a stack that logs nothing at all healthy. Not `==`
        either -- `1 == True` in Python, so a service answering an integer
        would be read as healthy.
        """
        assert FailoverLoggerProxy(RecordingService(True), "m").is_healthy() is True
        assert FailoverLoggerProxy(RecordingService(False), "m").is_healthy() is False
        assert FailoverLoggerProxy(
            RecordingService(ALL_SERVICES_FAILED), "m"
        ).is_healthy() is False
        assert FailoverLoggerProxy(RecordingService(1), "m").is_healthy() is False


class TestTheAuditProxyForwards:
    """Every audit event has to reach the failover service."""

    @pytest.mark.parametrize(
        "method, expected",
        [
            ("log_url_created", "log_url_created"),
            ("log_url_accessed", "log_url_accessed"),
            ("log_url_deleted", "log_url_deleted"),
        ],
    )
    def test_each_event_reaches_the_service_under_its_own_name(
        self, method, expected
    ):
        """
        Args:
            method: Proxy method being exercised.
            expected: Name it must forward under.
        """
        service = RecordingService()
        proxy = FailoverAuditLoggerProxy(service)

        getattr(proxy, method)("abc123", "https://example.com")

        assert len(service.calls) == 1
        name, args, _ = service.calls[0]
        assert name == expected
        assert args == ("abc123", "https://example.com")

    @pytest.mark.parametrize(
        "method", ["log_url_created", "log_url_accessed", "log_url_deleted"]
    )
    def test_bound_fields_travel_with_every_event(self, method):
        """
        The audit trail is worth little without who and from where.

        Every one of the three, not just creation: the access record is
        the one written most often -- every redirect writes one -- and it
        was the one nothing checked.

        Args:
            method: Audit method being exercised.
        """
        service = RecordingService()
        proxy = FailoverAuditLoggerProxy(service).bind(user_id="u-1")

        getattr(proxy, method)(
            "abc123", "https://example.com", ip="10.0.0.1"
        )

        _, _, kwargs = service.calls[0]
        assert kwargs["user_id"] == "u-1"
        assert kwargs["ip"] == "10.0.0.1"

    def test_a_second_binding_keeps_the_first_ones_fields(self):
        """
        Binding twice must add, not replace the whole set.

        A `bind` that starts from the new fields alone drops the request
        context the moment anything binds a second field to the same
        proxy.
        """
        service = RecordingService()
        proxy = FailoverAuditLoggerProxy(service).bind(user_id="u-1")

        proxy.bind(remote_addr="10.0.0.1").log_url_created(
            "abc123", "https://example.com"
        )

        _, _, kwargs = service.calls[0]
        assert kwargs["user_id"] == "u-1"
        assert kwargs["remote_addr"] == "10.0.0.1"

    def test_the_event_wins_over_a_bound_field_of_the_same_name(self):
        """
        The merge order, on the half where it changes who did what.

        Bound fields are the request context -- who is signed in, from
        where -- and the event's own arguments are what happened. Merging
        the bound fields last lets the context overwrite the event, so a
        record about one account is written down against another: an
        administrator deleting somebody else's link produces a trail
        naming the administrator as the owner. The swap passes everything
        else in the suite.
        """
        service = RecordingService()
        proxy = FailoverAuditLoggerProxy(service).bind(
            user_id="whoever-asked", request_id="req-1"
        )

        proxy.log_url_deleted(
            "abc123", "https://example.com", user_id="whose-link-it-was"
        )

        _, _, kwargs = service.calls[0]
        assert kwargs["user_id"] == "whose-link-it-was"
        assert kwargs["request_id"] == "req-1"

    def test_binding_does_not_change_the_proxy_it_came_from(self):
        """
        The audit half of the same rule, and the costlier half.

        A bind that mutates the proxy it was called on leaves one request's
        user id stamped on the next request's audit records -- which is the
        trail saying somebody did something they did not do.
        """
        service = RecordingService()
        original = FailoverAuditLoggerProxy(service)

        bound = original.bind(user_id="u-1")
        original.log_url_created("abc123", "https://example.com")

        assert bound is not original
        _, _, kwargs = service.calls[0]
        assert "user_id" not in kwargs

    def test_health_is_true_only_when_the_service_answers_true(self):
        """An audit trail that records nothing must not report health."""
        assert FailoverAuditLoggerProxy(RecordingService(True)).is_healthy() is True
        assert FailoverAuditLoggerProxy(
            RecordingService(ALL_SERVICES_FAILED)
        ).is_healthy() is False
        assert FailoverAuditLoggerProxy(RecordingService(1)).is_healthy() is False


class TestABoundFieldNamedLikeAnEventArgument:
    """
    The one shape of binding that can break the call.

    ``log_url_created`` passes ``short_code`` and ``original_url``
    positionally and everything else as keywords, so a bound field of
    either name arrived twice: ``TypeError: got multiple values for
    argument 'short_code'``. Both implementations refused it, the record
    was lost, ``dropped_calls`` grew and the chain moved to the standby --
    all over a mistake in the proxy, not in any logger.
    """

    @pytest.mark.parametrize(
        "method", ["log_url_created", "log_url_accessed", "log_url_deleted"]
    )
    @pytest.mark.parametrize("field", ["short_code", "original_url"])
    def test_the_call_still_goes_through(self, method, field):
        service = RecordingService()
        proxy = FailoverAuditLoggerProxy(service).bind(**{field: "bound value"})

        getattr(proxy, method)("abc123", "https://example.com")

        assert len(service.calls) == 1
        _, args, kwargs = service.calls[0]
        assert args == ("abc123", "https://example.com")
        assert field not in kwargs

    def test_the_event_keeps_its_own_values(self):
        """Dropping the bound name is not the same as dropping the event.

        What must reach the trail is the code that was actually created,
        not the one somebody bound to the request earlier.
        """
        service = RecordingService()
        proxy = FailoverAuditLoggerProxy(service).bind(
            short_code="from-the-binding", request_id="req-1"
        )

        proxy.log_url_created("from-the-event", "https://example.com")

        _, args, kwargs = service.calls[0]
        assert args[0] == "from-the-event"
        assert kwargs["request_id"] == "req-1"

    def test_other_bound_fields_are_untouched(self):
        """Only the two colliding names go."""
        service = RecordingService()
        proxy = FailoverAuditLoggerProxy(service).bind(
            short_code="dropped", user_id="u-1", remote_addr="10.0.0.1"
        )

        proxy.log_url_deleted("abc123", "https://example.com")

        _, _, kwargs = service.calls[0]
        assert kwargs == {"user_id": "u-1", "remote_addr": "10.0.0.1"}


class TestABareExceptionCallCarriesATraceback:
    """The default that made ``log.exception`` print a line without one.

    ``exc_info`` defaulted to ``None`` here, and the renderer skips a falsy
    value -- so the ordinary spelling, the one ``logging`` and ``structlog``
    both accept, produced something that reads like a traceback and has
    none. Flipping the default back to ``False`` passes everything else,
    because every call in ``src/`` passes ``exc_info`` explicitly.
    """

    def test_the_default_asks_for_the_exception_being_handled(self):
        service = RecordingService()
        proxy = FailoverLoggerProxy(service, "module")

        try:
            raise ValueError("boom")
        except ValueError:
            proxy.exception("it broke")

        _, _, kwargs = service.calls[0]
        assert kwargs["exc_info"] is True

    def test_an_explicit_exception_is_passed_through(self):
        service = RecordingService()
        error = ValueError("boom")

        FailoverLoggerProxy(service, "module").exception("it broke", exc_info=error)

        _, _, kwargs = service.calls[0]
        assert kwargs["exc_info"] is error

    def test_none_still_means_no_traceback(self):
        service = RecordingService()

        FailoverLoggerProxy(service, "module").exception("line", exc_info=None)

        _, _, kwargs = service.calls[0]
        assert kwargs["exc_info"] is None


class TestTheAuditProxyForwardsSecurityEvents:
    """The family that arrives through one method rather than three.

    The proxy forwards by method name, so a security event that never
    reaches ``FailoverService.execute`` is a login the trail does not
    record -- and nothing else in the suite would notice, because the
    adapters below the proxy are tested against their own callers.
    """

    def test_the_event_reaches_the_service_under_its_own_name(self):
        service = RecordingService()
        proxy = FailoverAuditLoggerProxy(service)

        proxy.log_security_event(AuditEvent.LOGIN_FAILED, reason="bad_password")

        assert len(service.calls) == 1
        name, args, kwargs = service.calls[0]
        assert name == "log_security_event"
        assert args == (AuditEvent.LOGIN_FAILED,)
        assert kwargs["reason"] == "bad_password"

    def test_the_named_wrappers_arrive_through_the_same_method(self):
        """They are concrete on the port, so the proxy inherits them.

        Which is the point of putting them there: the proxy gained the
        whole family by implementing one method, and a wrapper added later
        needs no change here at all.
        """
        service = RecordingService()
        proxy = FailoverAuditLoggerProxy(service)

        proxy.log_login_succeeded("u-1", "ivanov@example.com")

        name, args, kwargs = service.calls[0]
        assert name == "log_security_event"
        assert args == (AuditEvent.LOGIN_SUCCEEDED,)
        assert kwargs["target_user_id"] == "u-1"

    def test_bound_fields_travel_with_a_security_event(self):
        """A login with no address it came from is half a record."""
        service = RecordingService()
        proxy = FailoverAuditLoggerProxy(service).bind(remote_addr="10.0.0.1")

        proxy.log_login_failed("ivanov@example.com", "bad_password")

        _, _, kwargs = service.calls[0]
        assert kwargs["remote_addr"] == "10.0.0.1"

    def test_a_bound_field_named_event_does_not_break_the_call(self):
        """``event`` is passed positionally, so a bound one arrives twice.

        The same shape as ``short_code`` on the link events: without the
        guard the implementations refuse the call with ``TypeError``,
        ``dropped_calls`` grows and the chain moves to the standby -- over
        a mistake in this proxy. And ``event`` is a name a binding can
        plausibly carry, since structlog spells the message itself that
        way.
        """
        service = RecordingService()
        proxy = FailoverAuditLoggerProxy(service).bind(event="bound value")

        proxy.log_security_event(AuditEvent.LOGIN_FAILED, reason="bad_password")

        assert len(service.calls) == 1
        _, args, kwargs = service.calls[0]
        assert args == (AuditEvent.LOGIN_FAILED,)
        assert "event" not in kwargs
