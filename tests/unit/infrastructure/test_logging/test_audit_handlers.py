"""Tests for the ``AuditLogger`` adapters.

The audit log is the record of who did what to which link. Fields silently
dropped or overwritten here are not noticed until someone needs the log.
"""

import logging
from unittest.mock import MagicMock

import pytest

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
        `configure_logging` gives the audit logger handlers of its own and
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
        logger, backend = self._logger()
        backend.debug.side_effect = RuntimeError("backend down")

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
        # The three fields the event is made of used to be overwritten by
        # the binding as well, so a logger bound with `original_url` filed
        # the address it was bound with instead of `mask_url(...)` of the
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
