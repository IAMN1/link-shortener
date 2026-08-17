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

from link_shortener.application.ports.journal_reader import Journal
from link_shortener.infrastructure.logging.journal_reader import (
    BLOCK, HARD_LIMIT, FileJournalReader,
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
