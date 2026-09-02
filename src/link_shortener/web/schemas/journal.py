"""What a page of a journal looks like on the wire.

The page carries more than its lines, and each of the extra fields answers a
question a reader would otherwise answer wrongly by themselves. "Is this the
whole journal?" is not the same question as "did this response fill up", and
a viewer that cannot tell them apart shows the start of a rotated file as
the beginning of history.

The lines go out as they were read -- oldest first -- rather than newest
first. A journal is read in the order it was written, and reversing it here
would mean every reader of this endpoint reverses it back.
"""

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from link_shortener.application.ports.journal_reader import (
    HARD_LIMIT, JournalFilter, JournalLine, JournalPage,
)
from link_shortener.application.use_cases.journals.read_journal import (
    DEFAULT_LINES,
)


STAMP_PREFIX = (
    r"^\d{4}"
    r"(-(0[1-9]|1[0-2])"
    r"(-(0[1-9]|[12]\d|3[01])"
    r"(T([01]\d|2[0-3])"
    r"(:[0-5]\d"
    r"(:[0-5]\dZ?)?)?)?)?)?$"
)
"""A whole ISO 8601 stamp in UTC, or any prefix of one that ends on a field.

The journals are stamped ``2026-08-18T10:46:53Z`` and nothing else, by one
constant, so a bound is compared against them as text and any prefix is a
meaningful bound: a year, a month, a day, an hour. What the pattern refuses
is a prefix cut mid-field -- ``2026-08-1`` would silently mean the 1st and
the 10th through 19th, which is not a range anybody asked for -- and
anything that is not a stamp at all. Each field is bounded to its real
range as well, so ``2026-13-45T99`` is a 400 rather than a bound that sorts
past every line in the file and answers "nothing found", which a caller
reads as "the journal is empty".

The ``Z`` belongs to the seconds and to nothing shorter. Accepted after any
prefix -- which it was -- it inverts the very comparison the prefix exists
for: the bound is compared against the stamp truncated to the bound's own
length, and ``Z`` sorts after every character a stamp can carry there, so
``since=2026-08-18Z`` excluded all of 18 August while ``since=2026-08-18``
included it. Two spellings of one day, one of them silently empty. There is
no zone to name on a date anyway: ISO 8601 hangs the designator on a time,
never on a day.
"""


class JournalQuery(BaseModel):
    """
    What a caller may ask for beyond the journal's name.

    Every field arrives in the query string, so every one is validated
    rather than read: ``limit`` decides how much work a request costs, and
    the deployment serves requests on ``gunicorn --worker-class sync``,
    where one request occupies a worker for its whole life.

    ``limit`` is refused above ``HARD_LIMIT`` instead of being silently
    trimmed to it. A caller who asked for ten thousand lines and got two
    thousand with no word has been told that the journal holds two thousand
    lines, which is a lie about the thing they came to read.

    Attributes:
        limit: Most lines to return, from one up to the reader's ceiling.
        archives: Whether to continue into the rotated files once the live
            journal is exhausted. Off by default: the newest archive is
            uncompressed but the rest are gzip, which cannot be read from
            the end, so a page that includes them costs whole files.
        follow: Whether this read continues one the caller already made --
            the viewer refreshing the tail it is displaying. It changes
            nothing about what comes back; it decides whether the read is
            recorded in the audit journal, so that a page polling every
            five seconds does not write twelve lines a minute into the
            journal it is showing. Off by default, which is the safe way
            round: a caller that says nothing is recorded.

    The narrowing terms are not listed here. They are the search, they are
    described once in ``openapi.JOURNAL_SEARCH_PARAMETERS``, and each one
    given is a further condition a line must meet.
    """

    limit: int = Field(default=DEFAULT_LINES, ge=1, le=HARD_LIMIT)
    archives: bool = False
    follow: bool = False

    event_type: Optional[str] = Field(default=None, max_length=64)
    account: Optional[str] = Field(default=None, max_length=64)
    remote_addr: Optional[str] = Field(default=None, max_length=64)
    short_code: Optional[str] = Field(default=None, max_length=64)
    since: Optional[str] = Field(default=None, pattern=STAMP_PREFIX)
    until: Optional[str] = Field(default=None, pattern=STAMP_PREFIX)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "limit": 200,
                "archives": False,
                "follow": False,
                "event_type": "LOGIN_FAILED",
                "since": "2026-08-18",
            }
        }
    )

    def to_filter(self) -> JournalFilter:
        """
        The search terms, as the reader takes them.

        Returns:
            The filter. Empty when nothing was asked for, which the reader
            treats as no filter at all rather than as a filter matching
            everything -- the difference is whether it scans.
        """
        return JournalFilter(
            event_type=self.event_type,
            account=self.account,
            remote_addr=self.remote_addr,
            short_code=self.short_code,
            since=self.since,
            until=self.until,
        )


class JournalLineSchema(BaseModel):
    """
    One line of a journal, parsed as far as it could be.

    Attributes:
        raw: The line as it was written, without its newline.
        fields: What parsed out of it, or an empty object when it did not
            parse as a JSON object.
        parsed: Whether ``fields`` came from the line or is merely empty.
            Sent rather than inferred from an empty ``fields``: a record
            genuinely holding no keys and a line nothing could read are
            different things, and a viewer marks the second.
        source: File the line came from -- the live journal or one of the
            archives beside it, so a reader can tell how far back they are
            looking without counting.
    """

    raw: str
    fields: dict = Field(default_factory=dict)
    parsed: bool
    source: str

    @classmethod
    def from_domain(cls, line: JournalLine) -> "JournalLineSchema":
        """
        Build from what the reader returned.

        Args:
            line: The line to convert.

        Returns:
            The response model.
        """
        return cls(
            raw=line.raw,
            fields=line.fields,
            parsed=line.parsed,
            source=line.source,
        )


class JournalPageResponse(BaseModel):
    """
    One read of one journal.

    Attributes:
        journal: Which journal this is, by the name the caller asked under.
        lines: The lines, oldest first.
        total_scanned: How many lines were looked at to produce them.
        reached_start: True only when there is nothing older to read at
            all -- false when the page filled first, and false when
            archives were left unread. The distinction it exists for is
            "nothing older exists" against "nothing older was read".
        files_read: Names of the files that were opened, newest first.
        oldest_available: Name of the oldest archive found beside the live
            journal, or null when there is none. It is how far back a
            question could reach, as against how far this answer did.
    """

    journal: str
    lines: List[JournalLineSchema]
    total_scanned: int
    reached_start: bool
    files_read: List[str]
    oldest_available: Optional[str] = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "journal": "application",
                "lines": [
                    {
                        "raw": (
                            '{"timestamp": "2026-08-17T09:12:44Z", '
                            '"level": "info", "event": "Link created"}'
                        ),
                        "fields": {
                            "timestamp": "2026-08-17T09:12:44Z",
                            "level": "info",
                            "event": "Link created",
                        },
                        "parsed": True,
                        "source": "application.log",
                    }
                ],
                "total_scanned": 1,
                "reached_start": False,
                "files_read": ["application.log"],
                "oldest_available": "application.log.7.gz",
            }
        }
    )

    @classmethod
    def from_domain(cls, journal: str, page: JournalPage) -> "JournalPageResponse":
        """
        Build from what the use case returned.

        Args:
            journal: The journal's name, as the caller spelled it.
            page: The page to convert.

        Returns:
            The response model.
        """
        return cls(
            journal=journal,
            lines=[JournalLineSchema.from_domain(line) for line in page.lines],
            total_scanned=page.total_scanned,
            reached_start=page.reached_start,
            files_read=list(page.files_read),
            oldest_available=page.oldest_available,
        )
