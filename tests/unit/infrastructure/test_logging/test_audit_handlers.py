"""Tests for the ``AuditLogger`` adapters.

The audit log is the record of who did what to which link. Fields silently
dropped or overwritten here are not noticed until someone needs the log.
"""

import logging
from unittest.mock import MagicMock

import pytest

from link_shortener.application.ports.logger.audit import AuditEvent
from link_shortener.infrastructure.logging.handlers.audit.null_audit import (
    NullAuditLogger,
)
from link_shortener.infrastructure.logging.handlers.audit.standard import (
    StandardAuditLogger,
)
from link_shortener.infrastructure.logging.handlers.audit.structlog import (
    StructlogAuditLogger,
)


LONG_URL = "https://example.com/" + "x" * 200


class RecordingHandler(logging.Handler):
    """Collects the records emitted to the logger it is attached to."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


@pytest.fixture
def audit_logger():
    """Build a ``StandardAuditLogger`` wired to a private handler.

    Deliberately not ``caplog``. The application's logging setup turns off
    propagation on the ``audit`` logger, so once any other test in the run
    has built an application, records from this namespace stop reaching the
    root handler ``caplog`` installs. These tests passed on their own and
    failed in the full suite for exactly that reason. Attaching a handler
    to the logger under test removes the dependency on global state.
    """
    touched = []

    def build(suffix: str):
        """Return an audit logger and the handler recording it.

        Args:
            suffix: Distinguishes this test's logger from the others.

        Returns:
            Tuple of (audit logger, recording handler).
        """
        name = f"audit.unittest.{suffix}"
        raw = logging.getLogger(name)
        handler = RecordingHandler()
        raw.handlers = [handler]
        raw.propagate = False
        raw.setLevel(logging.DEBUG)
        touched.append(raw)
        return StandardAuditLogger(name), handler

    yield build

    for raw in touched:
        raw.handlers = []


class TestStandardAuditLogger:
    """Audit adapter over ``logging``."""

    @pytest.mark.parametrize(
        "method, event_type",
        [
            ("log_url_created", "URL_CREATED"),
            ("log_url_accessed", "URL_ACCESSED"),
            ("log_url_deleted", "URL_DELETED"),
        ],
    )
    def test_each_event_is_tagged_with_its_type(
        self, audit_logger, method, event_type
    ):
        """The event type is what makes the log searchable."""
        logger, handler = audit_logger(f"types.{event_type}")

        getattr(logger, method)("abc123", "https://example.com/")

        record = handler.records[-1]
        assert record.event_type == event_type
        assert record.short_code == "abc123"

    def test_long_url_is_shortened_before_it_is_written(self, audit_logger):
        logger, handler = audit_logger("mask")

        logger.log_url_created("abc123", LONG_URL)

        assert handler.records[-1].original_url != LONG_URL
        assert len(handler.records[-1].original_url) < len(LONG_URL)

    def test_extra_context_is_carried(self, audit_logger):
        logger, handler = audit_logger("extra")

        logger.log_url_created(
            "abc123", "https://example.com/", batch_id="b-1", is_new=True
        )

        record = handler.records[-1]
        assert record.batch_id == "b-1"
        assert record.is_new is True

    def test_bind_returns_a_new_logger(self):
        base = StandardAuditLogger("audit.unittest.bind")
        bound = base.bind(request_id="req-1")

        assert bound is not base
        assert base._bound_fields == {}
        assert bound._bound_fields == {"request_id": "req-1"}

    def test_bound_fields_reach_the_record(self, audit_logger):
        logger, handler = audit_logger("bound")

        logger.bind(
            request_id="req-1", remote_addr="10.0.0.1"
        ).log_url_accessed("abc123", "https://example.com/")

        record = handler.records[-1]
        assert record.request_id == "req-1"
        assert record.remote_addr == "10.0.0.1"

    def test_unhealthy_when_no_handler_can_be_reached(self):
        """Read by the failover service to decide whether to switch.

        Cut off from the root as well, because the question is whether a
        record reaches a handler rather than whether this logger owns one:
        `setup_logging` gives the audit logger handlers of its own and
        stops propagation, but a configuration that let audit records travel
        to the root would still be one that writes them.
        """
        logger = StandardAuditLogger("audit.unittest.health.none")
        logger._logger.handlers = []
        logger._logger.propagate = False
        try:
            assert logger.is_healthy() is False
        finally:
            logger._logger.propagate = True

    def test_healthy_with_a_handler(self):
        logger = StandardAuditLogger("audit.unittest.health.some")
        logger._logger.addHandler(logging.NullHandler())
        try:
            assert logger.is_healthy() is True
        finally:
            logger._logger.handlers = []


class TestStructlogAuditLogger:
    """Audit adapter over structlog."""

    @staticmethod
    def _logger():
        """Return an adapter over a recording stand-in."""
        backend = MagicMock()
        backend.bind.return_value = backend
        return StructlogAuditLogger(bound_logger=backend), backend

    @pytest.mark.parametrize(
        "method, event_type",
        [
            ("log_url_created", "URL_CREATED"),
            ("log_url_accessed", "URL_ACCESSED"),
            ("log_url_deleted", "URL_DELETED"),
        ],
    )
    def test_each_event_is_tagged_with_its_type(self, method, event_type):
        logger, backend = self._logger()

        getattr(logger, method)("abc123", "https://example.com/")

        _, kwargs = backend.info.call_args
        assert kwargs["event_type"] == event_type
        assert kwargs["short_code"] == "abc123"

    def test_long_url_is_shortened_before_it_is_written(self):
        logger, backend = self._logger()

        logger.log_url_created("abc123", LONG_URL)

        _, kwargs = backend.info.call_args
        assert kwargs["original_url"] != LONG_URL

    def test_bind_returns_a_new_logger(self):
        logger, _ = self._logger()

        bound = logger.bind(request_id="req-1")

        assert bound is not logger
        assert logger._bound_fields == {}
        assert bound._bound_fields == {"request_id": "req-1"}

    def test_bound_fields_reach_the_backend(self):
        logger, backend = self._logger()

        logger.bind(request_id="req-1").log_url_created(
            "abc123", "https://example.com/"
        )

        _, kwargs = backend.info.call_args
        assert kwargs["request_id"] == "req-1"

    def test_reports_unhealthy_when_the_backend_fails(self):
        # ``log``, not ``debug``: the probe is written at the level this
        # chain passes records at, because a ``DEBUG`` one was dropped by
        # the audit handlers -- they are ``INFO`` whatever ``LOG_LEVEL``
        # says -- before it could fail on anything.
        logger, backend = self._logger()
        backend.log.side_effect = RuntimeError("backend down")

        assert logger.is_healthy() is False

    def test_reports_healthy_otherwise(self):
        logger, _ = self._logger()

        assert logger.is_healthy() is True


class TestBoundFieldPrecedenceIsTheSameInBothImplementations:
    """One rule for a field named at both the binding and the call.

    The call wins. The failover service swaps the audit implementation on
    its own, without anyone asking, so a field name used in both places had
    a value that depended on which adapter happened to be active --
    ``StandardAuditLogger`` merged as ``{**bound, **call}`` while
    ``StructlogAuditLogger`` applied the binding last.

    The call is also what structlog itself lets win: ``_process_event``
    copies the context and then updates it with the call's keywords.
    """

    def test_the_binding_cannot_reach_around_the_masking(self):
        # The three fields the event is made of must not be overwritten by
        # the binding: a logger bound with `original_url` would file the
        # address it was bound with instead of `mask_url(...)` of the
        # one the event was about.
        backend = MagicMock()
        backend.bind.return_value = backend
        logger = StructlogAuditLogger(bound_logger=backend)

        logger.bind(
            event_type="BOUND_TYPE",
            short_code="BOUND",
            original_url="https://user:secret@bound/",
        ).log_url_created("abc123", LONG_URL)

        _, kwargs = backend.info.call_args
        assert kwargs["event_type"] == "URL_CREATED"
        assert kwargs["short_code"] == "abc123"
        assert kwargs["original_url"] != "https://user:secret@bound/"
        assert kwargs["original_url"] != LONG_URL

    def test_the_same_holds_against_a_real_structlog_backend(self):
        # The tests around this one use a MagicMock, whose `bind` does
        # nothing -- so they hold the adapter's own merge and not what a
        # record ends up saying. Here the real library resolves the
        # collision, over a logger that keeps what it was given.
        import structlog

        captured = []

        def capture(logger, method_name, event_dict):
            captured.append(dict(event_dict))
            raise structlog.DropEvent

        structlog.configure(processors=[capture])
        try:
            logger = StructlogAuditLogger()
            logger.bind(source="bound", short_code="BOUND").log_url_created(
                "abc123", "https://example.com/", source="call"
            )
        finally:
            structlog.reset_defaults()

        assert captured, "the backend recorded nothing"
        assert captured[-1]["source"] == "call"
        assert captured[-1]["short_code"] == "abc123"

    def test_standard_lets_the_call_site_win(self, audit_logger):
        logger, handler = audit_logger("precedence")

        logger.bind(source="bound").log_url_created(
            "abc123", "https://example.com/", source="call"
        )

        assert handler.records[-1].source == "call"

    def test_structlog_lets_the_call_site_win_too(self):
        backend = MagicMock()
        backend.bind.return_value = backend
        logger = StructlogAuditLogger(bound_logger=backend)

        logger.bind(source="bound").log_url_created(
            "abc123", "https://example.com/", source="call"
        )

        _, kwargs = backend.info.call_args
        assert kwargs["source"] == "call"

    def test_a_bound_field_the_call_says_nothing_about_still_arrives(self):
        # The change is about collisions only: what the call does not name
        # comes from the binding as before.
        backend = MagicMock()
        backend.bind.return_value = backend
        logger = StructlogAuditLogger(bound_logger=backend)

        logger.bind(request_id="req-1").log_url_created(
            "abc123", "https://example.com/"
        )

        _, kwargs = backend.info.call_args
        assert kwargs["request_id"] == "req-1"


class TestNullAuditLogger:
    """The do-nothing implementation used when auditing is off."""

    def test_every_event_is_silent(self):
        """Nothing must reach any handler, wherever one is attached.

        Watched at the root, because a null logger that quietly wrote
        somewhere would still be writing.
        """
        handler = RecordingHandler()
        root = logging.getLogger()
        root.addHandler(handler)
        previous_level = root.level
        root.setLevel(logging.DEBUG)
        try:
            logger = NullAuditLogger()

            logger.log_url_created("abc123", "https://example.com/")
            logger.log_url_accessed("abc123", "https://example.com/")
            logger.log_url_deleted("abc123", "https://example.com/")
            logger.log_login_failed("ivanov@example.com", "bad_password")
            logger.log_security_event(AuditEvent.LOGIN_SUCCEEDED, user_id="u-1")

            assert handler.records == []
        finally:
            root.removeHandler(handler)
            root.setLevel(previous_level)

    def test_bind_returns_itself(self):
        """Nothing is stored, so there is nothing to copy."""
        logger = NullAuditLogger()

        assert logger.bind(request_id="req-1") is logger

    def test_reports_healthy(self):
        assert NullAuditLogger().is_healthy() is True


WRAPPERS = [
    (
        lambda log: log.log_login_succeeded("u-1", "ivanov@example.com"),
        "LOGIN_SUCCEEDED",
    ),
    (lambda log: log.log_login_failed("ivanov@example.com", "bad"), "LOGIN_FAILED"),
    (lambda log: log.log_user_created("u-1", "a@b.com", ["admin"]), "USER_CREATED"),
    (lambda log: log.log_user_deleted("u-1", 3), "USER_DELETED"),
    (lambda log: log.log_user_activated("u-1"), "USER_ACTIVATED"),
    (lambda log: log.log_user_deactivated("u-1", 2), "USER_DEACTIVATED"),
    (
        lambda log: log.log_user_email_confirmed("u-1", False),
        "USER_EMAIL_CONFIRMED",
    ),
    (lambda log: log.log_email_confirmed("u-1"), "EMAIL_CONFIRMED"),
    (lambda log: log.log_roles_changed("u-1", [], ["admin"]), "ROLES_CHANGED"),
    (lambda log: log.log_password_changed("u-1", 2), "PASSWORD_CHANGED"),
    (lambda log: log.log_password_reset("u-1", 2), "PASSWORD_RESET"),
    (
        lambda log: log.log_user_password_reset("u-1", 2),
        "USER_PASSWORD_RESET",
    ),
    (lambda log: log.log_role_created("editor", ["link:create"]), "ROLE_CREATED"),
    (lambda log: log.log_role_deleted("editor", 7), "ROLE_DELETED"),
    (
        lambda log: log.log_role_permissions_changed(
            "editor", ["a"], ["a", "b"], 4
        ),
        "ROLE_PERMISSIONS_CHANGED",
    ),
    (
        lambda log: log.log_unverified_accounts_swept(3, 5),
        "UNVERIFIED_ACCOUNTS_SWEPT",
    ),
    (lambda log: log.log_audit_viewed("audit", "opened"), "AUDIT_VIEWED"),
    (
        lambda log: log.log_permission_denied(["admin:manage_roles"]),
        "PERMISSION_DENIED",
    ),
]
"""Every named wrapper on the port, and the event type it must reach.

A list rather than a parametrize block written twice: the two adapters are
swapped by the failover service without anyone asking, so a wrapper checked
against one of them and not the other is checked against a coin toss.
"""

LINK_EVENTS = {
    AuditEvent.URL_CREATED,
    AuditEvent.URL_ACCESSED,
    AuditEvent.URL_DELETED,
}
"""The three that came first and have methods of their own, not wrappers."""


class TestSecurityEvents:
    """Events about an account rather than about a link.

    They arrive through one method on the adapters and five named wrappers
    above it, so what is tested here is that the wrappers reach the right
    event type, that the address is masked on the way, and that the event
    type is the one thing a caller cannot talk the adapter out of.
    """

    @staticmethod
    def _structlog():
        """Return a structlog adapter over a recording stand-in."""
        backend = MagicMock()
        backend.bind.return_value = backend
        return StructlogAuditLogger(bound_logger=backend), backend

    @pytest.mark.parametrize("call, event_type", WRAPPERS)
    def test_each_wrapper_reaches_its_own_event_type(
        self, audit_logger, call, event_type
    ):
        """A wrapper that reached the wrong type files one event as another."""
        logger, handler = audit_logger(f"security.{event_type}")

        call(logger)

        assert handler.records[-1].event_type == event_type

    @pytest.mark.parametrize("call, event_type", WRAPPERS)
    def test_the_structlog_adapter_agrees(self, call, event_type):
        """The failover service swaps the two without asking anyone."""
        logger, backend = self._structlog()

        call(logger)

        _, kwargs = backend.info.call_args
        assert kwargs["event_type"] == event_type

    def test_every_event_in_the_vocabulary_can_be_written(self, audit_logger):
        """The enum and the adapters are checked against each other.

        A member added to ``AuditEvent`` that no adapter can write is a
        search term that will always answer "none", and nothing else in the
        suite would say so.
        """
        logger, handler = audit_logger("security.vocabulary")

        for event in AuditEvent:
            logger.log_security_event(event)

        written = {record.event_type for record in handler.records}
        assert written == {event.value for event in AuditEvent}

    def test_every_security_event_has_a_wrapper_of_its_own(self):
        """The enum and the wrappers are checked against each other too.

        ``log_security_event`` will write anything it is handed, so a
        member added to ``AuditEvent`` with no wrapper above it passes the
        test before this one and still has no typed way to be written --
        which means the next call site invents its own field names and the
        search built on them finds half the records.

        The three link events are excluded because they came first and
        have methods of their own rather than wrappers.
        """
        covered = {event_type for _, event_type in WRAPPERS}
        expected = {
            event.value for event in AuditEvent if event not in LINK_EVENTS
        }

        assert covered == expected

    def test_a_refusal_writes_only_the_half_that_applies(self, audit_logger):
        """An empty field is not information, and both are empty by turns.

        An ordinary refusal names a permission the caller lacks; an
        escalation attempt names the set they tried to hand out. Writing
        both always put ``"exceeded": []`` on every record of the first
        kind and ``"required": []`` on every record of the second --
        which is what ``_terms_of`` refuses to do for a search, and for
        the same reason.
        """
        logger, handler = audit_logger("security.refusal")

        logger.log_permission_denied(required=["audit:view"])
        logger.log_permission_denied(exceeded=["admin:all"])

        refused, escalated = handler.records[-2:]
        assert refused.required == ["audit:view"]
        assert not hasattr(refused, "exceeded")
        assert escalated.exceeded == ["admin:all"]
        assert not hasattr(escalated, "required")

    def test_the_address_is_masked_on_the_way_in(self, audit_logger):
        logger, handler = audit_logger("security.mask")

        logger.log_login_failed("ivanov@example.com", "bad_password")

        assert handler.records[-1].email == "i***@example.com"

    def test_the_structlog_adapter_masks_it_too(self):
        """Both, or the masking depends on which adapter is active."""
        logger, backend = self._structlog()

        logger.log_login_failed("ivanov@example.com", "bad_password")

        _, kwargs = backend.info.call_args
        assert kwargs["email"] == "i***@example.com"

    def test_an_address_bound_as_email_is_masked_as_well(self, audit_logger):
        """The rule is the name, not the argument position."""
        logger, handler = audit_logger("security.mask.bound")

        logger.bind(email="ivanov@example.com").log_security_event(
            AuditEvent.LOGIN_SUCCEEDED, user_id="u-1"
        )

        assert handler.records[-1].email == "i***@example.com"

    def test_the_structlog_adapter_masks_a_bound_address_too(self):
        """Both adapters, or binding is a way around the mask on one of them.

        It was, on the standard one: its ``_log`` merges the bound fields
        after the event's, so an address bound under ``email`` arrived past
        the masking and reached the record whole.
        """
        logger, backend = self._structlog()

        logger.bind(email="ivanov@example.com").log_security_event(
            AuditEvent.LOGIN_SUCCEEDED, user_id="u-1"
        )

        _, kwargs = backend.info.call_args
        assert kwargs["email"] == "i***@example.com"

    def test_the_call_cannot_file_one_event_under_another_type(
        self, audit_logger
    ):
        """Where this method parts company with the link events.

        There the call site wins over the event's own fields. Here it does
        not, and only for ``event_type``: a login written as ``URL_ACCESSED``
        is not a record with a wrong field in it -- it is a login that a
        search for logins never returns.
        """
        logger, handler = audit_logger("security.override.call")

        logger.log_security_event(
            AuditEvent.LOGIN_FAILED, event_type="URL_ACCESSED"
        )

        assert handler.records[-1].event_type == "LOGIN_FAILED"

    def test_the_binding_cannot_either(self, audit_logger):
        logger, handler = audit_logger("security.override.bound")

        logger.bind(event_type="URL_ACCESSED").log_security_event(
            AuditEvent.LOGIN_FAILED
        )

        assert handler.records[-1].event_type == "LOGIN_FAILED"

    def test_the_structlog_adapter_refuses_the_override_too(self):
        logger, backend = self._structlog()

        logger.bind(event_type="BOUND").log_security_event(
            AuditEvent.LOGIN_FAILED, event_type="CALL"
        )

        _, kwargs = backend.info.call_args
        assert kwargs["event_type"] == "LOGIN_FAILED"

    def test_a_role_change_records_both_sides(self, audit_logger):
        """"Now an administrator" and "was already one" are the same record
        with only the second half."""
        logger, handler = audit_logger("security.roles")

        logger.log_roles_changed("u-1", ["user"], ["user", "admin"])

        record = handler.records[-1]
        assert record.roles_before == ["user"]
        assert record.roles_after == ["user", "admin"]

    def test_a_refused_login_says_why(self, audit_logger):
        """The reason the HTTP response deliberately withholds."""
        logger, handler = audit_logger("security.reason")

        logger.log_login_failed("ivanov@example.com", "account_deactivated")

        assert handler.records[-1].reason == "account_deactivated"

    def test_bound_context_reaches_a_security_event(self, audit_logger):
        """Who did it is bound, not passed -- as with every other event."""
        logger, handler = audit_logger("security.context")

        logger.bind(request_id="req-1", remote_addr="10.0.0.1").log_login_failed(
            "ivanov@example.com", "bad_password"
        )

        record = handler.records[-1]
        assert record.request_id == "req-1"
        assert record.remote_addr == "10.0.0.1"

    def test_a_read_with_no_filter_still_carries_the_field(self, audit_logger):
        """Empty rather than absent: a reader comparing two records should
        not have to tell "searched for nothing" from "field missing"."""
        logger, handler = audit_logger("security.filters")

        logger.log_audit_viewed("audit", "opened")

        assert handler.records[-1].filters == {}
