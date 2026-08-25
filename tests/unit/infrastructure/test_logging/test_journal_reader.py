"""Reading a journal back from the end, across the files rotation leaves.

Three properties are worth holding here and none of them is obvious from
the code:

  - the answer is the *last* N lines, in the order they were written, and
    the block boundary the reader walks backwards through falls wherever it
    falls -- a line torn by it must not reach a caller;
  - a page that stopped because it was full and a page that stopped because
    the journal ran out are different answers, and a reader that cannot
    tell them apart concludes there is nothing older;
  - the front of the live file is never read, whatever its size. That one
    is checked by a file large enough that reading it whole would show.

The archives are the awkward half. `logrotate` leaves `application.log.1`
uncompressed -- `delaycompress`, so a tail can finish -- and everything
older as `.gz`, so both shapes exist beside a live journal at once and a
read that walks back far enough meets them in that order.
"""

import gzip
import json

import pytest

from link_shortener.application.ports.journal_reader import (
    HEALTH_PROBE_EVENT_TYPE, Journal, JournalFilter,
)
from link_shortener.infrastructure.logging.journal_reader import (
    BLOCK, HARD_LIMIT, SCAN_LIMIT, FileJournalReader, _lines_backwards,
)


def record(index: int, level: str = "info") -> str:
    """One line in the shape the journals actually carry.

    Args:
        index: Number to identify the line by.
        level: Level to write on it.

    Returns:
        The line, without its newline.
    """
    return json.dumps({
        "event": f"line {index}",
        "level": level,
        "logger": "live.check",
        "timestamp": "2026-08-17T10:44:13Z",
        "index": index,
    })


@pytest.fixture
def journals(tmp_path):
    """A log directory, and a way to fill its files.

    Args:
        tmp_path: Directory the journals are written into.

    Returns:
        The reader, the directory, and a writer taking a file name and the
        lines to put in it.
    """
    def write(name: str, lines, packed: bool = False):
        # logrotate renames as it compresses, so a packed generation is
        # `audit.log.2.gz` and never `audit.log.2` holding gzip bytes.
        path = tmp_path / (f"{name}.gz" if packed else name)
        body = "".join(f"{line}\n" for line in lines).encode()
        if packed:
            path.write_bytes(gzip.compress(body))
        else:
            path.write_bytes(body)
        return path

    reader = FileJournalReader(
        log_dir=str(tmp_path),
        file_names={
            Journal.APPLICATION: "application",
            Journal.ERROR: "error",
            Journal.AUDIT: "audit",
        },
    )
    return reader, tmp_path, write


class TestTheEndOfTheJournal:

    def test_it_returns_the_last_lines_oldest_first(self, journals):
        reader, _dir, write = journals
        write("audit.log", [record(i) for i in range(100)])

        page = reader.tail(Journal.AUDIT, limit=5)

        assert [line.fields["index"] for line in page.lines] == [95, 96, 97, 98, 99]

    def test_a_line_torn_by_the_block_boundary_never_reaches_a_caller(self, journals):
        """The reader walks backwards in blocks; lines do not align to them.

        The file is built so that the boundary is certain to fall inside a
        line rather than between two, and every line returned is then asked
        to parse. A fragment would arrive as unparsed and be caught here --
        the check is on the shape of the answer, not on the arithmetic that
        produced it.
        """
        reader, _dir, write = journals
        # Comfortably more than one block, with lines long enough that no
        # boundary can land cleanly between two of them.
        padded = [
            json.dumps({"event": "x" * 300, "index": i, "level": "info"})
            for i in range(int(BLOCK / 200))
        ]
        write("audit.log", padded)

        page = reader.tail(Journal.AUDIT, limit=50)

        assert len(page.lines) == 50
        assert all(line.parsed for line in page.lines), (
            "a fragment of a line was returned as a line"
        )
        assert [line.fields["index"] for line in page.lines] == list(
            range(len(padded) - 50, len(padded))
        )

    def test_asking_for_more_than_the_journal_holds_reaches_its_start(self, journals):
        reader, _dir, write = journals
        write("audit.log", [record(i) for i in range(10)])

        page = reader.tail(Journal.AUDIT, limit=500)

        assert len(page.lines) == 10
        assert page.reached_start is True

    def test_a_full_page_does_not_claim_to_have_reached_the_start(self, journals):
        """The difference between "nothing older" and "nothing older read".

        A page that filled says `reached_start=False` even when the file it
        read happens to be small, because what stopped it was the limit.
        """
        reader, _dir, write = journals
        write("audit.log", [record(i) for i in range(10)])

        page = reader.tail(Journal.AUDIT, limit=3)

        assert len(page.lines) == 3
        assert page.reached_start is False

    def test_a_journal_that_does_not_exist_is_an_empty_page(self, journals):
        """An operator who has never had an error is not an error.

        `error.log` is created on the first error and may genuinely be
        absent, and so is any journal on a deployment that has just
        started. Raising here would turn that into a failed request.
        """
        reader, _dir, _write = journals

        page = reader.tail(Journal.ERROR, limit=10)

        assert page.lines == ()
        assert page.files_read == ()


class TestTheCeilingOnOneRead:

    def test_a_caller_cannot_ask_for_more_than_the_hard_limit(self, journals):
        """The number arrives from a request and is not trusted.

        Without the cap a caller asking for ten million lines asks a sync
        worker to spend itself building the answer, and the four of them
        are the whole service.
        """
        reader, _dir, write = journals
        write("audit.log", [record(i) for i in range(HARD_LIMIT + 500)])

        page = reader.tail(Journal.AUDIT, limit=10_000_000)

        assert len(page.lines) == HARD_LIMIT

    @pytest.mark.parametrize("limit", [0, -1, -100])
    def test_nothing_is_read_for_a_limit_of_nothing(self, journals, limit):
        reader, _dir, write = journals
        write("audit.log", [record(i) for i in range(10)])

        page = reader.tail(Journal.AUDIT, limit=limit)

        assert page.lines == ()
        assert page.files_read == ()


class TestTheArchivesBesideIt:

    def test_the_live_journal_alone_unless_the_archives_are_asked_for(self, journals):
        reader, _dir, write = journals
        write("audit.log", [record(i) for i in range(90, 100)])
        write("audit.log.1", [record(i) for i in range(80, 90)])

        page = reader.tail(Journal.AUDIT, limit=50)

        assert [line.fields["index"] for line in page.lines] == list(range(90, 100))
        assert page.files_read == ("audit.log",)
        assert page.reached_start is False, (
            "the archives were not read, so older lines exist and were not "
            "reached -- saying otherwise invites the reader to conclude the "
            "journal begins where this deployment's rotation cut it"
        )

    def test_the_read_continues_into_the_archives_when_asked(self, journals):
        reader, _dir, write = journals
        write("audit.log", [record(i) for i in range(90, 100)])
        write("audit.log.1", [record(i) for i in range(80, 90)])

        page = reader.tail(Journal.AUDIT, limit=15, include_archives=True)

        assert [line.fields["index"] for line in page.lines] == list(range(85, 100))
        assert page.files_read == ("audit.log", "audit.log.1")

    def test_a_compressed_archive_is_read_like_any_other(self, journals):
        """`.gz` cannot be read from the end, and the caller cannot tell.

        gzip is a stream, so those are walked forwards behind a window of
        the wanted size -- the whole file in time, never more than the
        window in memory. What comes out is the same answer.
        """
        reader, _dir, write = journals
        write("audit.log", [record(i) for i in range(90, 100)])
        write("audit.log.1", [record(i) for i in range(80, 90)])
        write("audit.log.2", [record(i) for i in range(70, 80)], packed=True)

        page = reader.tail(Journal.AUDIT, limit=25, include_archives=True)

        assert [line.fields["index"] for line in page.lines] == list(range(75, 100))
        assert page.files_read == ("audit.log", "audit.log.1", "audit.log.2.gz")

    def test_generations_are_read_newest_first_not_alphabetically(self, journals):
        """Ten sorts before two as a string, and is newer as a generation.

        With more than nine generations -- and `audit.log` keeps 200 --
        sorting the names would put `.10` between `.1` and `.2` and hand
        back history out of order.
        """
        reader, _dir, write = journals
        write("audit.log", [record(999)])
        for generation in range(1, 12):
            write(f"audit.log.{generation}", [record(generation)])

        page = reader.tail(Journal.AUDIT, limit=4, include_archives=True)

        assert page.files_read == (
            "audit.log", "audit.log.1", "audit.log.2", "audit.log.3",
        )
        assert [line.fields["index"] for line in page.lines] == [3, 2, 1, 999]

    def test_the_oldest_archive_is_named_even_when_it_is_not_read(self, journals):
        """How far back a question *could* reach, as against how far it did.

        Without it a page of ten lines from the live journal looks the same
        whether a year of history sits beside it or nothing does.
        """
        reader, _dir, write = journals
        write("audit.log", [record(i) for i in range(10)])
        write("audit.log.1", [record(50)])
        write("audit.log.2", [record(51)], packed=True)

        page = reader.tail(Journal.AUDIT, limit=5)

        assert page.oldest_available == "audit.log.2.gz"
        assert page.files_read == ("audit.log",)

    def test_a_file_from_another_journal_is_not_mistaken_for_an_archive(self, journals):
        """All three journals share a directory.

        `application.log.1` sits beside `audit.log`, and a pattern anchored
        loosely enough would read one journal's history into the other's
        page.
        """
        reader, _dir, write = journals
        write("audit.log", [record(1)])
        write("application.log", [record(2)])
        write("application.log.1", [record(3)])

        page = reader.tail(Journal.AUDIT, limit=50, include_archives=True)

        assert page.files_read == ("audit.log",)
        assert page.oldest_available is None


class TestALineThatIsNotARecord:

    def test_it_is_returned_rather_than_dropped(self, journals):
        """A viewer that omits what it cannot parse is least trustworthy
        exactly when it matters: a write torn by rotation, a traceback a
        library printed itself, a partial line at the end of a file being
        appended to right now.
        """
        reader, _dir, write = journals
        write("audit.log", [record(1), "this is not JSON at all", record(2)])

        page = reader.tail(Journal.AUDIT, limit=10)

        assert len(page.lines) == 3
        middle = page.lines[1]
        assert middle.parsed is False
        assert middle.fields == {}
        assert middle.raw == "this is not JSON at all"

    def test_valid_json_that_is_not_an_object_counts_as_unparsed(self, journals):
        """`42` and `"hello"` are valid JSON and are not records.

        Returned as parsed with no fields, such a line reads as "a record
        with nothing in it" rather than "not a record".
        """
        reader, _dir, write = journals
        write("audit.log", ["42", '"a bare string"'])

        page = reader.tail(Journal.AUDIT, limit=10)

        assert [line.parsed for line in page.lines] == [False, False]
        assert [line.raw for line in page.lines] == ["42", '"a bare string"']

    def test_every_line_says_which_file_it_came_from(self, journals):
        reader, _dir, write = journals
        write("audit.log", [record(2)])
        write("audit.log.1", [record(1)])

        page = reader.tail(Journal.AUDIT, limit=10, include_archives=True)

        assert [line.source for line in page.lines] == ["audit.log.1", "audit.log"]


class TestItDoesNotReadWhatItDoesNotNeed:

    def test_a_large_journal_is_answered_from_its_end(self, journals):
        """The measurement this class exists for.

        Reading a gigabyte whole cost 2.5 s and a 1.8 GB peak; the same
        answer from the end costs 5.2 ms. A megabyte here is enough to
        prove the shape -- the file is far larger than one block, and the
        read must still touch only the end of it.
        """
        reader, tmp_path, write = journals
        lines = [record(i) for i in range(20_000)]
        path = write("audit.log", lines)
        assert path.stat().st_size > 20 * BLOCK, "the fixture is too small to prove anything"

        page = reader.tail(Journal.AUDIT, limit=10)

        assert [line.fields["index"] for line in page.lines] == list(range(19_990, 20_000))
        # Read backwards, the whole file is never held: what was scanned is
        # the page itself rather than the twenty thousand lines behind it.
        assert page.total_scanned == 10


class TestAWideReadCostsWhatANarrowOneDoes:
    """The buffer is joined once rather than rebuilt on every block.

    Written ``buffer = handle.read(step) + buffer``, the walk backwards
    rebuilds everything it has read on each step, which is quadratic in the
    number of steps. At a page of 200 lines the loop takes two steps and
    nothing shows; the cost only appears once a read scans far past what it
    returns, which is what a filter does. Measured on this tree, the two
    spellings are 1.6 ms against 0.3 ms for 2000 lines and 3144 ms against
    13.9 ms for 100 000, with the peak following to 2.3 GB.

    The check is a wall-clock ceiling, which is a shape worth defending: it
    is here because the property is *cost*, and no assertion about the
    lines returned can see it -- the old spelling returns exactly the same
    answer. The ceiling is set two orders of magnitude above the measured
    time and one below the old one, so it takes a real regression to trip
    and a machine 70 times slower than this one to trip it falsely.
    """

    def test_a_hundred_thousand_lines_are_read_in_well_under_a_second(
        self, journals
    ):
        """The line length is part of the measurement, not decoration.

        The cost is quadratic in the number of *blocks*, so it is the size
        of the file that drives it and not the number of lines. Written
        with this module's short `record`, 100 000 lines make 11.7 MB, the
        old spelling takes 350 ms and a ceiling generous enough to be safe
        does not catch it -- which is what happened when this test was
        first written. A line the width of a real audit record, 357 bytes,
        makes 35.8 MB and the old spelling takes 3087 ms.
        """
        import time

        reader, tmp_path, write = journals
        # Padded to the width of a real `URL_ACCESSED` record, measured at
        # 473 bytes on this tree and 357 in the shape written here.
        padding = "x" * 260
        path = write(
            "audit.log",
            [record(i).replace('"level"', f'"filler": "{padding}", "level"')
             for i in range(100_000)],
        )
        assert path.stat().st_size > 30_000_000, "the fixture is too small to prove anything"

        started = time.perf_counter()
        lines, reached_start = _lines_backwards(path, 100_000)
        elapsed = time.perf_counter() - started

        assert len(lines) == 100_000
        assert reached_start is True
        assert elapsed < 0.5, (
            f"reading 100 000 lines took {elapsed * 1000:.0f} ms; the joined "
            "buffer does it in about 14, the rebuilt one in about 3100"
        )

    def test_the_same_holds_for_an_archive_that_is_walked_forwards(
        self, journals, tmp_path
    ):
        """The compressed branch had the fault the plain one was fixed for.

        gzip cannot be read from the end, so the archive is walked
        forwards while a window of the wanted lines is held -- and the
        window was a list trimmed with `pop(0)`, which moves every entry
        still in it, once per line of the file. Harmless while the window
        was `HARD_LIMIT`; a filtered read asks for `SCAN_LIMIT`, twenty
        five times as far to move. Measured on this tree over 200 000
        lines at a window of 50 000: 0.89 s against 0.04 s.
        """
        import gzip
        import time

        path = tmp_path / "audit.log.4.gz"
        with gzip.open(path, "wb") as handle:
            handle.write(
                ("\n".join(record(i) for i in range(200_000)) + "\n").encode()
            )

        started = time.perf_counter()
        lines, reached_start = _lines_backwards(path, SCAN_LIMIT)
        elapsed = time.perf_counter() - started

        assert len(lines) == SCAN_LIMIT
        assert reached_start is True
        # The last line of the file is the newest, and it must still be
        # the last of the window: speed bought by returning the wrong end
        # would be no bargain.
        assert json.loads(lines[-1])["index"] == 199_999
        assert elapsed < 0.5, (
            f"reading the archive took {elapsed * 1000:.0f} ms; the bounded "
            "window does it in about 40, the trimmed list in about 890"
        )

    def test_the_lines_are_the_same_ones_the_slow_spelling_returned(
        self, journals
    ):
        """Speed is not the property if the answer changed with it.

        The tail is computed here the obvious way -- the whole file in
        memory, which is what the reader exists to avoid -- and the two are
        compared. Every page size in the list crosses a different number of
        block boundaries.
        """
        reader, tmp_path, write = journals
        written = [record(i) for i in range(5_000)]
        path = write("audit.log", written)

        for wanted in (1, 2, 199, 1_000, 4_998, 4_999, 5_000, 5_001):
            lines, reached_start = _lines_backwards(path, wanted)

            assert lines == written[-wanted:], f"page of {wanted} differs"

        # Asserted only where it is defined by the file rather than by the
        # block size. A page far smaller than the file cannot have reached
        # the start; a page asking for everything must have. In between,
        # the last step overshoots by up to a block, so whether the start
        # was touched depends on where the boundary happens to fall -- and
        # a test pinning that would be pinning ``BLOCK``.
        assert _lines_backwards(path, 100)[1] is False
        assert _lines_backwards(path, 5_001)[1] is True


class TestSearchingRatherThanTailing:
    """A filter changes what the page size means.

    Without one, the reader stops as soon as it holds the lines it was
    asked for, and the size of the file stops mattering. With one it has to
    keep looking past them -- so the second number in the answer,
    ``total_scanned``, stops being decoration and becomes the difference
    between "there is nothing" and "there is nothing in what was looked
    at".
    """

    def test_only_the_matching_lines_come_back(self, journals):
        reader, tmp_path, write = journals
        write("audit.log", [
            json.dumps({"event_type": "URL_ACCESSED", "index": 0}),
            json.dumps({"event_type": "LOGIN_FAILED", "index": 1}),
            json.dumps({"event_type": "URL_ACCESSED", "index": 2}),
            json.dumps({"event_type": "USER_CREATED", "index": 3}),
        ])

        page = reader.tail(
            Journal.AUDIT, limit=10, where=JournalFilter(event_type="LOGIN_FAILED")
        )

        assert [line.fields["index"] for line in page.lines] == [1]

    def test_the_page_still_holds_the_newest_of_them(self, journals):
        """The last N *matching* lines, in the order they were written."""
        reader, tmp_path, write = journals
        write("audit.log", [
            json.dumps({"event_type": "LOGIN_FAILED", "index": i})
            if i % 2 else json.dumps({"event_type": "URL_ACCESSED", "index": i})
            for i in range(100)
        ])

        page = reader.tail(
            Journal.AUDIT, limit=3, where=JournalFilter(event_type="LOGIN_FAILED")
        )

        assert [line.fields["index"] for line in page.lines] == [95, 97, 99]

    def test_what_was_looked_at_is_reported_apart_from_what_was_found(
        self, journals
    ):
        """Without this the page cannot say "one match in ten thousand
        lines" as against "one match, and one line"."""
        reader, tmp_path, write = journals
        write("audit.log", [
            json.dumps({"event_type": "LOGIN_FAILED" if i == 0 else "URL_ACCESSED"})
            for i in range(500)
        ])

        page = reader.tail(
            Journal.AUDIT, limit=10, where=JournalFilter(event_type="LOGIN_FAILED")
        )

        assert len(page.lines) == 1
        assert page.total_scanned == 500

    def test_an_empty_filter_reads_the_plain_tail(self, journals):
        """It must not cost the window: a filter with nothing in it is the
        page every poll of the viewer asks for."""
        reader, tmp_path, write = journals
        write("audit.log", [record(i) for i in range(1_000)])

        page = reader.tail(Journal.AUDIT, limit=5, where=JournalFilter())

        assert [line.fields["index"] for line in page.lines] == [995, 996, 997, 998, 999]
        assert page.total_scanned == 5

    def test_the_window_bounds_how_far_a_search_looks(self, journals):
        """A search for something that is not there must not walk the file.

        The ceiling is `SCAN_LIMIT`; this checks the shape of the stop
        rather than the number, by asking for something absent from a file
        longer than the window it is given.
        """
        reader, tmp_path, write = journals
        write("audit.log", [json.dumps({"event_type": "URL_ACCESSED"})
                            for _ in range(SCAN_LIMIT + 500)])

        page = reader.tail(
            Journal.AUDIT, limit=10, where=JournalFilter(event_type="NOTHING_LIKE_IT")
        )

        assert page.lines == ()
        assert page.total_scanned == SCAN_LIMIT
        # The window ran out, not the journal -- and saying otherwise would
        # tell a reader the account they are looking for was never here.
        assert page.reached_start is False

    def test_a_short_journal_searched_to_its_start_says_so(self, journals):
        """The other half of the same distinction."""
        reader, tmp_path, write = journals
        write("audit.log", [json.dumps({"event_type": "URL_ACCESSED"})
                            for _ in range(50)])

        page = reader.tail(
            Journal.AUDIT, limit=10, where=JournalFilter(event_type="NOTHING_LIKE_IT")
        )

        assert page.lines == ()
        assert page.total_scanned == 50
        assert page.reached_start is True

    def test_a_search_continues_into_the_archives_when_asked(self, journals):
        reader, tmp_path, write = journals
        write("audit.log", [json.dumps({"event_type": "URL_ACCESSED"})
                            for _ in range(10)])
        write("audit.log.1", [json.dumps({"event_type": "LOGIN_FAILED", "index": 1})])

        without = reader.tail(
            Journal.AUDIT, limit=10, where=JournalFilter(event_type="LOGIN_FAILED")
        )
        with_them = reader.tail(
            Journal.AUDIT, limit=10, include_archives=True,
            where=JournalFilter(event_type="LOGIN_FAILED"),
        )

        assert without.lines == ()
        assert [line.fields["index"] for line in with_them.lines] == [1]

    def test_a_line_that_did_not_parse_is_left_out_of_a_search(self, journals):
        """Kept in a plain tail, dropped by a filter: it has no fields to
        match on, and letting it through would answer a search for one
        account with every torn line in the file."""
        reader, tmp_path, write = journals
        write("audit.log", [
            "{not json at all",
            json.dumps({"event_type": "LOGIN_FAILED", "index": 7}),
        ])

        plain = reader.tail(Journal.AUDIT, limit=10)
        searched = reader.tail(
            Journal.AUDIT, limit=10, where=JournalFilter(event_type="LOGIN_FAILED")
        )

        assert len(plain.lines) == 2
        assert [line.fields["index"] for line in searched.lines] == [7]


def probe_record(index: int) -> str:
    """One line in the shape the chains' own health probe writes.

    Args:
        index: Number to identify the line by.

    Returns:
        The line, without its newline.
    """
    return json.dumps({
        "event": "logging chain health probe",
        "event_type": HEALTH_PROBE_EVENT_TYPE,
        "level": "info",
        "logger": "audit",
        "timestamp": "2026-08-17T10:44:13Z",
        "index": index,
    })


class TestTheChainsOwnProbeIsNotPartOfTheTail:
    """
    The probe writes into the journal it is probing, and a reader did not
    come for it.

    Eight lines a minute per journal at four workers and the seeded
    interval -- measured on the running stack -- which filled 25 of the 50
    lines on the first screen of the journals page. ``JournalFilter``
    drops them; this is the half that keeps the page full anyway.
    """

    def test_the_plain_tail_leaves_them_out(self, journals):
        reader, _dir, write = journals
        write("audit.log", [probe_record(1), record(2), probe_record(3)])

        page = reader.tail(Journal.AUDIT, limit=10)

        assert [line.fields["index"] for line in page.lines] == [2]

    def test_the_page_still_fills_up(self, journals):
        """Dropping records must not shorten the window that was asked for.

        A plain tail reads exactly the page it was asked for, so with the
        probes interleaved a window of five came back holding two. It
        looks further now, and only when it has to.
        """
        reader, _dir, write = journals
        lines = []
        for index in range(1, 41):
            lines.append(probe_record(index))
            lines.append(record(index))
        write("audit.log", lines)

        page = reader.tail(Journal.AUDIT, limit=5)

        assert len(page.lines) == 5
        assert page.total_scanned > 5

    def test_a_journal_without_probes_is_read_as_cheaply_as_before(
        self, journals
    ):
        """The cost of looking further is paid only where it buys something.

        Measured on this tree: a plain tail costs 0.3 ms and a full scan
        17 ms, and on a gigabyte the same two are 2 ms and 117 ms. A
        journal nothing was dropped from must not pay the second.
        """
        reader, _dir, write = journals
        write("application.log", [record(index) for index in range(1, 101)])

        page = reader.tail(Journal.APPLICATION, limit=10)

        assert len(page.lines) == 10
        assert page.total_scanned == 10

    def test_asking_for_the_probe_by_name_returns_it(self, journals):
        reader, _dir, write = journals
        write("audit.log", [probe_record(1), record(2)])

        page = reader.tail(
            Journal.AUDIT, limit=10,
            where=JournalFilter(event_type=HEALTH_PROBE_EVENT_TYPE),
        )

        assert [line.fields["index"] for line in page.lines] == [1]

    def test_a_journal_that_is_all_probes_reads_as_empty(self, journals):
        """And says so rather than looking for ever.

        The deep re-read is bounded by ``SCAN_LIMIT`` like any other
        scan, and a file it exhausts reports that it reached the start.
        """
        reader, _dir, write = journals
        write("audit.log", [probe_record(index) for index in range(1, 21)])

        page = reader.tail(Journal.AUDIT, limit=10)

        assert page.lines == ()
        assert page.reached_start is True
