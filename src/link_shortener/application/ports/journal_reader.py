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


HEALTH_PROBE_EVENT_TYPE = "LOGGING_CHAIN_PROBE"
"""The ``event_type`` the logging chains write their own health probe under.

The probe is a real record -- it has to be, or it would not find out
whether the chain can still write -- so it lands in the journal it is
probing, once per chain per check interval per worker: measured at eight
lines a minute in each of ``application.log`` and ``audit.log`` on four
workers at the seeded interval. Left unmarked it filled 25 of the 50
lines on the first screen of the journals page, which is a reader coming
to see what happened and being shown the service checking itself.

Named here rather than in the logging package because this is where it is
acted on: ``JournalFilter`` drops these lines unless the caller asks for
this exact type, and that makes the existing search the way to see them
-- no new switch on the page, no second vocabulary. The lines stay in the
file either way: a gap in them is how a reader afterwards can tell the
chain stopped writing.
"""


@dataclass(frozen=True)
class JournalFilter:
    """What a caller is looking for in a journal, if anything.

    Every field is optional and an empty filter matches everything, which
    is what makes it safe to pass one always: the reader asks whether it
    is empty rather than whether it exists.

    Matching is exact on the identifiers and by prefix on the times. Exact,
    because these are identifiers and a substring of one is not a weaker
    version of the question -- ``remote_addr`` containing ``10.0.0.1``
    would also answer for ``110.0.0.199``, which is a different machine.
    Prefix on the times, because the stamps are ISO 8601 in UTC and
    therefore sort as text: ``2026-08-18`` reads as the whole of that day
    at either end of the range, ``2026-08-18T14`` as that hour, with no
    parsing and no clock arithmetic.

    A line that did not parse matches nothing. It has no fields to match
    on, so a filter cannot say anything about it -- the alternative,
    letting unparsed lines through every filter, would answer a search for
    one account with every torn line in the file.

    Attributes:
        event_type: The event's own name, from ``AuditEvent``'s vocabulary.
        account: An account id, matched against ``user_id`` *and*
            ``target_user_id``. One field rather than two because the
            question an investigation brings is "everything about this
            account", and the events split across those two names by
            whether the account acted or was acted upon -- searching one
            name is a way to see half of what happened and not notice.
        remote_addr: The address a request came from.
        short_code: The link an event was about.
        since: Earliest stamp to include, as a prefix of one.
        until: Latest stamp to include, as a prefix of one.
    """

    event_type: Optional[str] = None
    account: Optional[str] = None
    remote_addr: Optional[str] = None
    short_code: Optional[str] = None
    since: Optional[str] = None
    until: Optional[str] = None

    @property
    def is_empty(self) -> bool:
        """Whether this filter asks for anything at all.

        Returns:
            ``True`` when every field is unset, so that a reader can take
            the cheap path and read exactly the page it was asked for.
        """
        return not any(
            (
                self.event_type,
                self.account,
                self.remote_addr,
                self.short_code,
                self.since,
                self.until,
            )
        )

    def matches(self, fields: dict) -> bool:
        """Whether one record answers this filter.

        Args:
            fields: What parsed out of the line, empty for a line that did
                not parse as a JSON object.

        Returns:
            ``True`` if every field that was asked for matches.
        """
        # Before the empty-filter shortcut, so that the plain tail -- the
        # read that has asked for nothing -- is the one this hides them
        # from. Asked for by name they come back, which is what makes the
        # search the way to see them.
        if fields.get("event_type") == HEALTH_PROBE_EVENT_TYPE:
            return self.event_type == HEALTH_PROBE_EVENT_TYPE

        if self.is_empty:
            return True

        if not fields:
            return False

        if self.event_type and fields.get("event_type") != self.event_type:
            return False

        if self.account and self.account not in (
            fields.get("user_id"),
            fields.get("target_user_id"),
        ):
            return False

        if self.remote_addr and fields.get("remote_addr") != self.remote_addr:
            return False

        if self.short_code and fields.get("short_code") != self.short_code:
            return False

        return self._within_the_range(fields.get("timestamp"))

    def _within_the_range(self, stamp) -> bool:
        """Whether a stamp falls inside the range asked for.

        Compared as text against a prefix of the same shape, which is what
        ISO 8601 in UTC is for. Truncating the stamp to the length of the
        bound is what makes both ends inclusive: with ``until`` given as a
        date, every moment of that date compares equal to it rather than
        after it, so a day named as the end of a range is part of it.

        Args:
            stamp: The record's ``timestamp``, or ``None`` if it has none.

        Returns:
            ``True`` if the stamp is within both bounds that were given.
        """
        if not (self.since or self.until):
            return True

        if not isinstance(stamp, str):
            # A record with no usable stamp cannot be placed in time, and
            # a search bounded by time is asking exactly where it falls.
            return False

        if self.since and stamp[:len(self.since)] < self.since:
            return False

        if self.until and stamp[:len(self.until)] > self.until:
            return False

        return True


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


HARD_LIMIT = 2000
"""Most lines one call may return, whatever it was asked for.

Here rather than in the implementation, because it is not the
implementation's business alone: the number arrives from a request, and the
caller that takes the request has to refuse an excess *before* the read
rather than discover it afterwards. ``JournalQuery`` bounds ``limit`` by
this, and a schema reaching into ``infrastructure`` for it was the web
layer importing a fact from the layer beneath the one it is allowed to
know.

The number itself is a measurement of the file reader: at the measured 473
bytes a line, two thousand lines is under a megabyte of response. It binds
every implementation all the same -- a caller told "at most this many" must
get the same answer from whichever reader is wired in, or the refusal it
gives is about the wrong ceiling.

The ceiling is on lines rather than bytes because a line's length is
bounded by what the application writes into it, while the count is bounded
by nothing at all.
"""


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
        where: Optional[JournalFilter] = None,
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
            where: What to look for, or ``None`` for the plain tail. A
                filter changes what the number of lines means: without one
                the reader stops as soon as it has that many, with one it
                keeps looking past them, so an implementation owes a
                ceiling of its own on how far it will go. What it looked
                at is reported as ``total_scanned``.

        Returns:
            The page, oldest line first.
        """
        raise NotImplementedError
