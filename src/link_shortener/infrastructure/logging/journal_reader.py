"""Reading the journals back, from the end, without reading the front.

Everything here exists because of one measurement. `audit.log` is capped at
a gigabyte between rotations, and on a gigabyte:

| reading the last 200 lines | time | peak RSS |
|---|---|---|
| whole file into memory | 2497 ms | 1845 MB |
| line by line from the top | 367 ms | constant |
| seek to the end, blocks backwards | 5.2 ms | constant |

Production is `gunicorn --worker-class sync --workers 4`, where a request
occupies a worker for its whole life. The first row is therefore not a slow
page but an outage: four of them and the service has no workers left, and
the 1.8 GB peak is a memory limit away from the container being killed.

So the file is opened for reading backwards and the front of it is never
touched. Size stops mattering: the same read costs 0.2 ms on 100 MB and 5.2
ms on a gigabyte, because what is read is the tail either way.
"""

import gzip
import json
import os
import re
from collections import deque
from pathlib import Path
from typing import IO, Deque, List, Optional, Tuple, cast

from link_shortener.application.ports.journal_reader import (
    HARD_LIMIT, Journal, JournalFilter, JournalLine, JournalPage,
    JournalReaderPort,
)

BLOCK = 64 * 1024
"""How much is read per step when walking a file backwards.

Large enough that an ordinary page of 200 lines at some 500 bytes each
arrives in two reads, small enough that the buffer stays trivial beside the
request that asked for it.
"""

SCAN_LIMIT = 50_000
"""Most lines one filtered read will look at before giving up.

Without a filter the reader stops as soon as it has the page it was asked
for, and size stops mattering. With one it has to keep looking, and how far
is a decision rather than a consequence: a search for something that is not
there would otherwise walk a gigabyte.

Measured end to end on this tree, against a 46 MB journal of records the
width the audit journal actually writes: a filtered read costs 117 to 136
ms whatever it is looking for, and an unfiltered tail of 200 lines costs 2
ms. The cost is flat across the terms because it is the scan that is paid
for, not the matching -- most of it is parsing 50 000 records, and a search
that finds nothing costs exactly what one finding a full page does.

That is a tenth of a second of a worker, on a deployment whose workers are
`gunicorn --worker-class sync --workers 4`. Doubling the window doubles it:
at 100 000 lines the buffer alone is 36 MB, and four searches at once would
be most of a small container.

At ten redirects a second the window is roughly an hour and a half of a
busy service and weeks of a quiet one. When it runs out the page says so:
`total_scanned` reaches this number while `reached_start` stays false, and
the two together are the difference between "there is nothing" and "there
is nothing in what was looked at".
"""

ARCHIVE = re.compile(r"^(?P<base>.+\.log)\.(?P<generation>\d+)(?P<packed>\.gz)?$")
"""What logrotate leaves beside a journal.

`application.log.1` is the previous generation, `application.log.2.gz` the
one before it, and so on to `rotate`. The newest archive is deliberately
left uncompressed by `delaycompress`, so whoever is still reading the file
can finish; both shapes therefore exist at once and both are read here.
"""


def _archives_of(path: Path) -> List[Path]:
    """The rotated generations beside a journal, newest first.

    Args:
        path: The live journal.

    Returns:
        Its archives, ordered as they should be read: generation 1, then 2,
        and so on backwards in time.
    """
    found = []
    for candidate in path.parent.iterdir():
        match = ARCHIVE.match(candidate.name)
        if match and match.group("base") == path.name:
            found.append((int(match.group("generation")), candidate))
    return [candidate for _generation, candidate in sorted(found)]


def _open(path: Path) -> IO[bytes]:
    """Open a journal or an archive for reading bytes.

    Args:
        path: File to open.

    Returns:
        A binary handle, decompressing on the fly where the name says to.
    """
    if path.suffix == ".gz":
        # ``GzipFile`` is a binary file object in every way this module
        # uses it -- iterated by line, closed by the context manager -- but
        # it does not declare ``IO[bytes]``.
        return cast(IO[bytes], gzip.open(path, "rb"))
    return path.open("rb")


def _lines_backwards(path: Path, wanted: int) -> Tuple[List[str], bool]:
    """The last ``wanted`` lines of a file, oldest of them first.

    A compressed archive cannot be read from the end -- gzip is a stream,
    and the last block is only reachable by inflating everything before it
    -- so those are walked forwards while holding a window of the last
    ``wanted`` lines. That costs the whole file in time but never more than
    the window in memory, which is the trade worth making: an archive is
    read when somebody asks for history, and the live journal, which is
    what nearly every request wants, is never read that way.

    Args:
        path: File to read.
        wanted: How many lines are wanted from its end.

    Returns:
        The lines, and whether the read reached the start of the file.
    """
    if path.suffix == ".gz":
        # A deque bounded to the window, rather than a list trimmed with
        # `pop(0)`: popping the front of a list moves every remaining
        # entry, once per line of the file, which is the same quadratic
        # shape the block loop below carries a comment about. It stayed
        # cheap only while the window was `HARD_LIMIT` -- a filtered read
        # raised it to `SCAN_LIMIT`, twenty-five times as far to move.
        # Measured on this tree over 200 000 lines: 0.90 s against 0.03 s
        # at a window of 50 000.
        window: Deque[str] = deque(maxlen=wanted)
        with _open(path) as handle:
            for raw in handle:
                window.append(raw.decode("utf-8", errors="replace").rstrip("\n"))
        return list(window), True

    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        position = handle.tell()
        # Blocks are kept apart and joined once, at the end. Written as
        # ``buffer = handle.read(step) + buffer`` the loop rebuilds the
        # whole buffer on every step, which is quadratic in the number of
        # steps and invisible at a page of 200 lines -- measured on this
        # tree, 1.6 ms for 2000 lines against 0.3 ms, and then 3144 ms
        # against 13.9 ms for 100 000, with the peak RSS following the same
        # curve to 2.3 GB. The page size never reached the second row until
        # a filter began scanning past what it returns.
        chunks: List[bytes] = []
        newlines = 0
        # One newline more than asked for, and that is what keeps a torn
        # line out of the answer. A block boundary lands mid-line nearly
        # always, so the first entry in the buffer is a fragment -- but the
        # loop only stops once the buffer holds more newlines than were
        # asked for, and the slice below therefore always has at least one
        # entry to discard from the front. The fragment is that entry.
        #
        # An explicit ``lines.pop(0)`` stood here for that job and did
        # nothing the slice was not already doing. Checked directly rather
        # than by the suite going green: line widths of 37 to 5000 bytes
        # against every page size from 1 to one past the end of the file,
        # comparing the result to the tail of the file computed in memory.
        while position > 0 and newlines <= wanted:
            step = min(BLOCK, position)
            position -= step
            handle.seek(position)
            chunk = handle.read(step)
            chunks.append(chunk)
            newlines += chunk.count(b"\n")

        # Reversed because the file was walked backwards: the last block
        # read is the earliest in the file.
        buffer = b"".join(reversed(chunks))

    reached_start = position == 0
    text = buffer.decode("utf-8", errors="replace")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        # The trailing newline of the last complete line, not a line.
        lines.pop()

    return lines[-wanted:], reached_start


def _parse(raw: str, source: str) -> JournalLine:
    """Turn one line of text into a journal line.

    Args:
        raw: The line as written.
        source: Name of the file it came from.

    Returns:
        The line, with its fields if it had any.
    """
    try:
        fields = json.loads(raw)
    except ValueError:
        return JournalLine(raw=raw, fields={}, parsed=False, source=source)

    if not isinstance(fields, dict):
        # A bare number or string is valid JSON and is not a record. It
        # would otherwise reach a caller as an object with no keys, which
        # reads as "a record with nothing in it" rather than "not a record".
        return JournalLine(raw=raw, fields={}, parsed=False, source=source)

    return JournalLine(raw=raw, fields=fields, parsed=True, source=source)


def _is_plain(where: Optional[JournalFilter]) -> bool:
    """
    Whether a read asked for nothing in particular.

    Args:
        where: The filter a caller passed, if any.

    Returns:
        ``True`` for the plain tail -- no filter, or one with every field
        unset.
    """
    return where is None or where.is_empty


class FileJournalReader(JournalReaderPort):
    """Reads the journals off the disk they are written to.

    Attributes:
        log_dir: Directory the journals live in.
        file_names: File name per journal, without the ``.log`` suffix,
            since all three are configurable.
    """

    def __init__(self, log_dir: str, file_names: dict):
        """
        Args:
            log_dir: Where the journals are.
            file_names: ``{Journal.AUDIT: "audit", ...}`` -- the base names
                the deployment configured.
        """
        self.log_dir = Path(log_dir)
        self.file_names = file_names

    def _path_of(self, journal: Journal) -> Path:
        """Where a journal lives.

        Args:
            journal: Which journal.

        Returns:
            Path of the live file.
        """
        return self.log_dir / f"{self.file_names[journal]}.log"

    def tail(
        self,
        journal: Journal,
        limit: int,
        include_archives: bool = False,
        where: Optional[JournalFilter] = None,
    ) -> JournalPage:
        """Read the most recent lines of a journal.

        Args:
            journal: Which journal to read.
            limit: Most lines to return, capped at ``HARD_LIMIT``.
            include_archives: Whether to continue into the rotated files
                once the live journal is exhausted.
            where: What to look for, or ``None`` for the plain tail.

        Returns:
            The page, oldest line first.
        """
        page = self._tail(journal, limit, include_archives, where)

        # A plain tail reads exactly the page it was asked for, because
        # without a filter a line looked at is a line returned. That
        # stopped being true when the chains' own health probe went into
        # the journals: ``JournalFilter`` drops it from a read that asked
        # for nothing, so a window of 50 came back holding 32 on a stack
        # where 36% of the audit journal was probes. Looking further is
        # paid for only where they actually took the page -- an unfiltered
        # tail costs 0.3 ms on this tree and a full scan 17 ms, and on a
        # gigabyte the same two are 2 ms and 117 ms.
        short = len(page.lines) < max(0, min(limit, HARD_LIMIT))
        if short and not page.reached_start and _is_plain(where):
            return self._tail(journal, limit, include_archives, where, deep=True)

        return page

    def _tail(
        self,
        journal: Journal,
        limit: int,
        include_archives: bool = False,
        where: Optional[JournalFilter] = None,
        deep: bool = False,
    ) -> JournalPage:
        """Read the most recent lines, looking as far as ``deep`` says.

        Args:
            journal: Which journal to read.
            limit: Most lines to return, capped at ``HARD_LIMIT``.
            include_archives: Whether to continue into the rotated files.
            where: What to look for, or ``None`` for the plain tail.
            deep: Whether to scan to ``SCAN_LIMIT`` even with no terms,
                which is what a page emptied by dropped records needs.

        Returns:
            The page, oldest line first.
        """
        wanted = max(0, min(limit, HARD_LIMIT))
        looking_for = where if where and not where.is_empty else JournalFilter()
        live = self._path_of(journal)
        archives = _archives_of(live) if live.parent.is_dir() else []
        oldest = archives[-1].name if archives else None

        if wanted == 0:
            return JournalPage(
                lines=(), total_scanned=0, reached_start=False,
                files_read=(), oldest_available=oldest,
            )

        collected: List[JournalLine] = []
        files_read: List[str] = []
        reached_start = False
        scanned = 0

        # How far this read may look, as against how much it may return.
        # They are the same number without a filter -- a line looked at is
        # a line returned -- and with one the reader keeps going past the
        # page it is filling, up to the ceiling it owes the deployment.
        budget = SCAN_LIMIT if (deep or not _is_plain(where)) else wanted

        # Newest first, and the collection is built backwards for the same
        # reason: the answer is "the last N lines", so a file is only
        # opened while N has not been reached.
        for path in [live, *(archives if include_archives else [])]:
            if not path.exists():
                continue

            room = budget - scanned
            if room <= 0:
                break

            lines, hit_start = _lines_backwards(path, room)
            files_read.append(path.name)
            scanned += len(lines)

            # Always, now that an empty filter is not the same as no
            # filter: it still drops the chains' own probe records, which
            # a reader did not come for. Costs nothing extra -- the lines
            # were parsed either way, on the line above.
            found = [
                line for line in (_parse(raw, path.name) for raw in lines)
                if looking_for.matches(line.fields)
            ]
            collected = found + collected
            reached_start = hit_start

            if len(collected) >= wanted or scanned >= budget:
                # Stopped because the page filled or the window ran out,
                # not because the journal did -- whatever the last file
                # said about its own start.
                reached_start = False
                break
        else:
            # Every file was read to its end, so there is genuinely nothing
            # older -- unless the archives were not asked for, in which case
            # what was reached is the start of the live file and no more.
            reached_start = reached_start and (include_archives or not archives)

        return JournalPage(
            lines=tuple(collected[-wanted:]),
            total_scanned=scanned,
            reached_start=reached_start,
            files_read=tuple(files_read),
            oldest_available=oldest,
        )
