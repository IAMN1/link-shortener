"""
Unit tests for ``MinimalLogger``.

The logger the failover service falls back on when nothing else is up yet,
including when the logging stack itself is what failed. Two things matter
about it and neither is obvious from the outside: it writes to stderr rather
than stdout, and it depends on nothing but the standard library.
"""

import datetime
import re

import pytest

from link_shortener.infrastructure.failover.minimal_logger import MinimalLogger


ENTRY = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \[(INFO|WARNING|ERROR)\] (.*)$"
)
"""The shape of one line: timestamp, bracketed level, then the message."""


class TestItWritesWhereTheOperatorIsLooking:

    @pytest.mark.parametrize("method", ["info", "warning", "error"])
    def test_output_goes_to_stderr_and_not_stdout(self, capsys, method):
        # stdout belongs to the program's own output. A log line printed
        # there lands in whatever the service was piped into. Checked on
        # every level, not only on info: the module docstring claims this
        # of the class, and one level leaking is a leak.
        getattr(MinimalLogger(), method)("bootstrapping")

        captured = capsys.readouterr()
        assert captured.out == ""
        assert ENTRY.match(captured.err.strip()).group(2) == "bootstrapping"


class TestEachLevelIsNamed:

    @pytest.mark.parametrize("method,level", [
        ("info", "INFO"),
        ("warning", "WARNING"),
        ("error", "ERROR"),
    ])
    def test_the_level_reaches_the_line(self, capsys, method, level):
        getattr(MinimalLogger(), method)("something happened")

        line = capsys.readouterr().err.strip()
        match = ENTRY.match(line)
        assert match, line
        assert match.group(1) == level
        assert match.group(2) == "something happened"


class TestTheLineIsReadable:

    def test_the_timestamp_is_now_and_not_merely_timestamp_shaped(self, capsys):
        before = datetime.datetime.now()
        MinimalLogger().warning("switched to standby")
        after = datetime.datetime.now()

        line = capsys.readouterr().err.strip()
        assert ENTRY.match(line), line
        # The shape alone is satisfied by a hardcoded 1970, and by a
        # timestamp seven hours out because it was built in the wrong zone.
        # Bracketed by two readings taken around the call, which is a
        # comparison the code cannot satisfy by construction.
        stamped = datetime.datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S")
        assert before.replace(microsecond=0) <= stamped
        assert stamped <= after + datetime.timedelta(seconds=1)

    def test_a_message_holding_brackets_is_not_mangled(self, capsys):
        MinimalLogger().error("Service [redis] failed for write: timeout")

        line = capsys.readouterr().err.strip()
        match = ENTRY.match(line)
        assert match
        assert match.group(2) == "Service [redis] failed for write: timeout"

    def test_a_long_message_is_not_truncated(self, capsys):
        # What this logger actually carries is
        # "Service X failed for Y: <exception text>", and an exception's
        # text is the part worth having. Every other message in this file
        # is short enough to survive a truncation nobody would notice.
        reason = "; ".join(["connection refused"] * 20)
        MinimalLogger().warning(f"Service redis failed for write: {reason}")

        line = capsys.readouterr().err.strip()
        assert ENTRY.match(line).group(2) == (
            f"Service redis failed for write: {reason}"
        )

    def test_a_message_with_newlines_keeps_them(self, capsys):
        # Exception text is exactly what arrives with newlines in it.
        MinimalLogger().error("first line\nsecond line")

        err = capsys.readouterr().err
        assert err == (
            f"{err[:19]} [ERROR] first line\nsecond line\n"
        )

    def test_one_call_writes_one_line(self, capsys):
        logger = MinimalLogger()
        logger.info("first")
        logger.error("second")

        lines = capsys.readouterr().err.strip().splitlines()
        assert len(lines) == 2
        assert ENTRY.match(lines[0]).groups() == ("INFO", "first")
        assert ENTRY.match(lines[1]).groups() == ("ERROR", "second")
