"""A record keeps its fields whichever adapter wrote it.

Two settings choose two halves of one journal line, and they are not the
same setting. ``LOGGER_TYPE`` decides the *formatter*, once, at start-up;
the *adapter* that hands the formatter a record is chosen by
``FailoverService``, which moves it at run time -- demoting ``structlog``
to ``standard`` is the whole reason that class exists.

So the ordinary state after any demotion is a ``standard`` record meeting
a ``ProcessorFormatter``. ``ProcessorFormatter`` runs the application's
chain only for records structlog made; everything else gets
``foreign_pre_chain`` and nothing more. Without ``ExtraAdder`` in that
chain the caller's own fields were dropped in silence:

    {"event": "Link created", "level": "info", "logger": "global",
     "timestamp": "..."}

-- no ``request_id``, no ``user_id``, no ``short_code``, and on the audit
side no ``event_type``. That is worse than an ugly line, because
``JournalFilter`` keys on exactly those names: a search by event type, by
account or by address answers *nothing* rather than "cannot say", and the
probe suppression on ``event_type`` stops firing, so the chain's own
health probes flood the plain tail a reader came to look at.

Held here on the formatter rather than through ``setup_logging`` so the
failure is about the one seam it lives on, and so the test says which of
the two halves is wrong when it goes red.
"""

import io
import json
import logging

import pytest
import structlog

from link_shortener.application.ports.journal_reader import JournalFilter
from link_shortener.application.ports.logger.audit import AuditEvent
from link_shortener.infrastructure.logging.bootstrap import FOREIGN_PRE_CHAIN
from link_shortener.infrastructure.logging.handlers.audit.standard import (
    StandardAuditLogger,
)
from link_shortener.infrastructure.logging.handlers.logger.standard import (
    StandardLogger,
)


@pytest.fixture
def written(request):
    """A logger whose records go through the file formatter, as JSON.

    The formatter is the one ``_file_formatter`` builds under
    ``LOGGER_TYPE=auto``, which is the shipped default, and the adapter is
    the one a demotion leaves behind.
    """
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=FOREIGN_PRE_CHAIN,
    ))

    name = f"probe-{request.node.name}"
    logger = logging.getLogger(name)
    logger.handlers = [handler]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    yield name, stream

    logger.handlers = []


class TestAStandardRecordKeepsWhatTheCallerBound:

    def test_the_bound_and_the_passed_fields_both_arrive(self, written):
        name, stream = written

        StandardLogger(name).bind(
            request_id="abc-123", user_id="u1"
        ).info("Link created", short_code="xyz")

        line = json.loads(stream.getvalue())
        assert line["event"] == "Link created"
        assert line["request_id"] == "abc-123"
        assert line["user_id"] == "u1"
        assert line["short_code"] == "xyz"

    def test_the_renamed_module_field_arrives_too(self, written):
        """``module`` is renamed by the adapter because ``LogRecord``
        refuses to be overwritten; the renamed one still has to reach the
        line, or a reader filtering the journal by source finds nothing."""
        name, stream = written

        StandardLogger(name).info("wrote", module="my.module")

        assert json.loads(stream.getvalue())["module_name"] == "my.module"

    def test_an_audit_record_keeps_the_field_the_search_reads(self, written):
        """``event_type`` is what ``JournalFilter`` matches on, so losing
        it is not a cosmetic loss -- it is a login that a search for
        logins never returns."""
        name, stream = written

        StandardAuditLogger(name).log_security_event(
            AuditEvent.LOGIN_FAILED, email="who@example.com", reason="bad"
        )

        line = json.loads(stream.getvalue())
        assert line["event_type"] == "LOGIN_FAILED"
        assert line["reason"] == "bad"

    def test_the_search_that_reads_them_finds_the_record(self, written):
        """The two halves joined: what the formatter wrote is what the
        journal filter is asked about. Without this the assertions above
        are about a shape nothing consumes."""
        name, stream = written

        StandardAuditLogger(name).log_security_event(
            AuditEvent.LOGIN_FAILED, email="who@example.com", reason="bad"
        )
        record = json.loads(stream.getvalue())

        assert JournalFilter(event_type="LOGIN_FAILED").matches(record) is True
        assert JournalFilter(event_type="LOGIN_SUCCEEDED").matches(record) is False


class TestALibrarysRecordIsUnaffected:

    def test_a_foreign_record_still_gets_its_three_fields(self, written):
        """The reason ``foreign_pre_chain`` exists in the first place:
        Celery's and werkzeug's lines carry neither a level nor a
        timestamp of their own."""
        name, stream = written

        logging.getLogger(name).info("Task received")

        line = json.loads(stream.getvalue())
        assert line["event"] == "Task received"
        assert line["level"] == "info"
        assert line["logger"] == name
        assert line["timestamp"]
