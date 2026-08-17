from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple


class Journal(Enum):
    """Which journal is being read.

    Named rather than passed as a path, and that is the whole security
    property of this port: a caller states *which of three* it wants, so a
    string arriving from a request can never become a path. The one that
    tried is answered by the enum refusing to construct.

    The names are these three because these are the three the application
    writes. Their file names come from ``LOG_FILENAME``,
    ``AUDIT_LOG_FILENAME`` and ``ERROR_LOG_FILENAME``, so what a member
    resolves to is a matter of configuration; which members exist is not.
    """

    APPLICATION = "application"
    ERROR = "error"
    AUDIT = "audit"


@dataclass(frozen=True)
class JournalLine:
    """One line of a journal, parsed as far as it can be.

    Not a dictionary, because a line that is not JSON is still a line an
    operator wants to see -- a partial write torn by rotation, a traceback
    a library printed itself. Such a line arrives with ``fields`` empty and
    ``raw`` holding what was on disk, and the reader says so rather than
    dropping it: a journal viewer that silently omits the malformed lines
    is at its least trustworthy exactly when it matters most.

    Attributes:
        raw: The line as it was written, without its newline.
        fields: What parsed out of it, or an empty mapping if it did not
            parse as a JSON object.
        parsed: Whether ``fields`` came from the line or is merely empty.
        source: Name of the file this line came from -- the live journal or
            one of the archives beside it, so a reader can tell how far
            back they are looking.
    """

    raw: str
    fields: dict
    parsed: bool
    source: str


@dataclass(frozen=True)
class JournalPage:
    """What one read returned, and what it could not reach.

    Attributes:
        lines: The lines, oldest first -- the order they were written in,
            whatever order they were read in.
        total_scanned: How many lines were looked at to produce them.
            With a filter in play this exceeds ``len(lines)``, and the
            difference is what the filter removed.
        reached_start: ``True`` only when there is nothing older to read at
            all. It is false when the page filled first, and false when
            unread archives sit behind the files that were read -- asking
            for the live journal alone leaves the archives behind it, and a
            reader told ``True`` there would conclude the journal begins
            where this deployment's rotation happens to have cut it. The
            distinction the field exists for is "nothing older exists"
            against "nothing older was read"; where the two are in doubt it
            answers the second.
        files_read: Names of the files that were opened, newest first.
        oldest_available: Name of the oldest archive found beside the live
            journal, or ``None`` when there is none. It is how far back a
            question could reach, as against how far this answer did.
    """

    lines: Tuple[JournalLine, ...]
    total_scanned: int
    reached_start: bool
    files_read: Tuple[str, ...]
    oldest_available: Optional[str]


class JournalReaderPort(ABC):
    """Reads the journals the application writes, and only those.

    The port exists because reading them is not a matter of opening a file.
    The live `audit.log` reaches a gigabyte between rotations by design,
    and reading a gigabyte into memory to show two hundred lines costs 2.5
    seconds and a 1.8 GB peak -- measured -- on a deployment whose workers
    are `gunicorn --worker-class sync`, where one such request occupies a
    worker entirely and four occupy the service. An implementation is
    obliged to answer from the end without reading the front.

    Nothing here writes, and there is no method that could: the journals
    are what an incident is reconstructed from, and an interface that could
    alter them would be the fault it is meant to guard against.
    """

    @abstractmethod
    def tail(
        self,
        journal: Journal,
        limit: int,
        include_archives: bool = False,
    ) -> JournalPage:
        """Read the most recent lines of a journal.

        Args:
            journal: Which journal to read.
            limit: Most lines to return. An implementation is expected to
                cap this itself as well: the number reaches it from a
                request, and a caller asking for ten million lines is
                asking the service to stop answering.
            include_archives: Whether to continue into the rotated files
                beside the live journal once it is exhausted.

        Returns:
            The page, oldest line first.
        """
        raise NotImplementedError
