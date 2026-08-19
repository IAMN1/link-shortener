"""
Time arithmetic in SQL, spelled for both engines this project runs on.

Here rather than in a repository because it is a property of the dialect
and not of a table. It was a private method on one repository, then the
same private method on a second, and the cost of that was measured: an
identical one-line defect -- ``cast(extract('epoch', ...), Integer)``
rounds on PostgreSQL where ``strftime('%s', ...)`` truncates -- had to be
found and fixed twice, on two branches, in two commits. The next
repository that buckets by time would have started with a third copy.

``_as_utc`` travelled the same way: two byte-identical module functions,
the second carrying a docstring that says "for the same reason the visit
repository does it".
"""

from datetime import datetime, timezone

from sqlalchemy import Integer, cast, extract, func
from sqlalchemy.orm import Session


DAY = 86400
"""Seconds in a day.

Exact, because every stamp here is UTC: no offset changes a day's length,
so ``epoch // DAY`` is the date.
"""


def epoch_seconds(session: Session, column):
    """
    Whole seconds since 1970, in whichever dialect is in use.

    Both engines truncate when dividing integers, and the bucket index is
    integer division -- so the seconds must be truncated too. PostgreSQL
    would otherwise *round*: ``extract`` yields the fraction as well, and
    casting a fractional value to an integer rounds to nearest, which put
    a visit at 23:59:59.7 on the following day. ``func.floor`` is what
    makes the two engines agree.

    Args:
        session: The session, asked which dialect it is bound to.
        column: A datetime column.

    Returns:
        An integer-valued SQL expression, truncated on both engines.
    """
    if session.get_bind().dialect.name == "sqlite":
        return cast(func.strftime("%s", column), Integer)

    return cast(func.floor(extract("epoch", column)), Integer)


def as_utc(moment: datetime) -> datetime:
    """
    Give a moment a timezone if the database handed it back without one.

    SQLite stores no offset, so every datetime read from it is naive and
    comparing one against an aware datetime raises. The values written are
    UTC, so reading them back as UTC is a restoration rather than an
    assumption.

    Args:
        moment: Datetime from the database or from a caller.

    Returns:
        The same moment, marked UTC when it carried no zone.
    """
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
