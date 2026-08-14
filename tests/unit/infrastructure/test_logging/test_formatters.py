"""Tests for the log formatters.

A formatter is the last thing a log line passes through, and its failures
are quiet: a dropped field or a raised exception inside formatting is
noticed long after the event it was meant to record.
"""

import json
import logging


from link_shortener.infrastructure.logging.formatters.console_formatter import (
    ConsoleFormatter,
)
from link_shortener.infrastructure.logging.formatters.json_formatter import (
    JSONFormatter,
)


def make_record(message="something happened", level=logging.INFO, **extra):
    """Build a LogRecord carrying the given extra fields.

    Args:
        message: The log message.
        level: Numeric log level.
        **extra: Fields the application attached to the record.

    Returns:
        A ``logging.LogRecord``.
    """
    record = logging.LogRecord(
        name="link_shortener.test",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


class TestJSONFormatter:
    """Serialisation of a record into one JSON object per line."""

    def test_emits_a_single_json_object(self):
        """The output has to parse, or the log is not machine-readable."""
        formatted = JSONFormatter().format(make_record())

        parsed = json.loads(formatted)
        assert parsed["event"] == "something happened"
        assert parsed["level"] == "info"
        assert parsed["logger"] == "link_shortener.test"
        assert "timestamp" in parsed

    def test_level_is_lowercased(self):
        """Pinned because downstream filters match on the string."""
        record = make_record(level=logging.WARNING)

        assert json.loads(JSONFormatter().format(record))["level"] == "warning"

    def test_extra_fields_are_included(self):
        """Structured logging is the entire point of this formatter."""
        record = make_record(request_id="req-1", user_id="u-9", clicks=3)

        parsed = json.loads(JSONFormatter().format(record))

        assert parsed["request_id"] == "req-1"
        assert parsed["user_id"] == "u-9"
        assert parsed["clicks"] == 3

    def test_message_arguments_are_interpolated(self):
        """``getMessage`` is what applies args -- not str(msg)."""
        record = logging.LogRecord(
            name="t", level=logging.INFO, pathname=__file__, lineno=1,
            msg="hello %s", args=("world",), exc_info=None,
        )

        assert json.loads(JSONFormatter().format(record))["event"] == "hello world"

    def test_unserialisable_field_is_dropped_not_raised(self):
        """One awkward value must not cost the whole log line.

        A formatter that raises inside ``format`` loses the record and
        prints a handler error instead, so an object nobody thought about
        would silently blind the log at exactly the moment it mattered.
        """
        class Opaque:
            __slots__ = ()

        record = make_record(good="kept", bad=Opaque())

        parsed = json.loads(JSONFormatter().format(record))

        assert parsed["good"] == "kept"
        assert "bad" not in parsed

    def test_non_ascii_is_preserved_by_default(self):
        """Russian text in a log should stay readable."""
        record = make_record(note="кириллица")

        formatted = JSONFormatter().format(record)

        assert "кириллица" in formatted
        assert json.loads(formatted)["note"] == "кириллица"

    def test_non_ascii_is_escaped_when_asked(self):
        """The flag has to actually do something."""
        record = make_record(note="кириллица")

        formatted = JSONFormatter(ensure_ascii=True).format(record)

        assert "кириллица" not in formatted
        assert json.loads(formatted)["note"] == "кириллица"


class TestConsoleFormatter:
    """The human-readable line."""

    def test_contains_logger_name_and_message(self):
        """The base line: timestamp - [name] - message."""
        formatted = ConsoleFormatter().format(make_record())

        assert "[link_shortener.test]" in formatted
        assert "something happened" in formatted

    def test_module_name_overrides_the_logger_name(self):
        """``StandardLogger`` renames ``module`` to ``module_name``.

        The rename exists because ``module`` collides with a built-in
        LogRecord attribute; this formatter is the other half of that
        arrangement, and it displays the renamed value.
        """
        record = make_record(module_name="link_shortener.web.api")

        formatted = ConsoleFormatter().format(record)

        assert "[link_shortener.web.api]" in formatted
        assert "[link_shortener.test]" not in formatted

    def test_extra_fields_are_appended(self):
        """Context is what makes a line useful after the fact."""
        record = make_record(request_id="req-7", clicks=2)

        formatted = ConsoleFormatter().format(record)

        assert "request_id=req-7" in formatted
        assert "clicks=2" in formatted

    def test_line_without_extras_has_no_trailing_bracket(self):
        """An empty bracket on every line is noise."""
        formatted = ConsoleFormatter().format(make_record())

        assert not formatted.rstrip().endswith("]")

    def test_non_primitive_value_is_shown_as_repr(self):
        """Formatting must survive an arbitrary object."""
        record = make_record(payload={"a": 1})

        formatted = ConsoleFormatter().format(record)

        assert "payload={'a': 1}" in formatted


class TestNoMachineryLeaksIntoOutput:
    """Neither formatter may present LogRecord's own attributes as data.

    Both kept a hand-written list of names to skip, and both fell behind
    the language: Python 3.12 added ``taskName``, so every console line
    ended in ``- [taskName=None]`` and every JSON line carried
    ``"taskName": null``. The lists are now derived from a real record, and
    these tests fail on the next attribute Python adds rather than after
    someone notices the noise in a log file.
    """

    def test_console_line_carries_no_record_internals(self):
        formatted = ConsoleFormatter().format(make_record())

        assert "taskName" not in formatted
        # No extras were supplied, so nothing should be appended at all.
        assert formatted.endswith("something happened")

    def test_json_line_carries_no_record_internals(self):
        parsed = json.loads(JSONFormatter().format(make_record()))

        assert "taskName" not in parsed
        assert set(parsed) == {"timestamp", "level", "logger", "event"}

    def test_a_future_record_attribute_would_be_caught(self):
        """The guard is the derived set, not the two names above.

        Simulates the next release adding an attribute: it must not appear
        in the output either, which is what a hand-written list could not
        promise.
        """
        record = make_record()
        record.someFutureAttr = "added by a later Python"
        # Present on the reference record too -- i.e. machinery, not payload.
        from link_shortener.infrastructure.logging import utils

        assert "taskName" in utils.STANDARD_RECORD_ATTRS
        assert "someFutureAttr" not in utils.STANDARD_RECORD_ATTRS
        # An attribute the machinery does NOT set is application data and
        # must still come through -- the fix must not silence real fields.
        assert "someFutureAttr" in ConsoleFormatter().format(record)
