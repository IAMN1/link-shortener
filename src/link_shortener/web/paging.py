"""
Reading the window a listing request asks for.

The third of the small modules that keep a decision in one place, beside
``web/responses.py`` and ``web/request_body.py``: one shapes an answer, one
reads a body, this one reads ``limit`` and ``offset`` off the query string.

It was made twice and the two disagreed. ``GET /api/v1/links/mine`` clamped
what it read -- floor of one, ceiling of two hundred, offset never below
zero -- and ``GET /api/v1/admin/users`` passed it straight through.
Measured on the running stack: ``?offset=-1`` and ``?limit=-5`` answered
500 on the admin listing and 200 on the link listing, the same request
meeting two different services. A negative ``OFFSET`` is not a query
PostgreSQL runs, and there is nothing for the caller to do about a 500.

The ceiling is the other half. Without it ``?limit=100000000`` was a
request for the whole table in one answer, built into as many entities and
serialised in one go -- which is a cost a caller sets and the service pays.
"""

from typing import Tuple

from flask import request


MAX_PAGE_SIZE = 200
"""
Most rows one listing answer may carry.

Not a rule about what may be read -- a caller entitled to the table can
still walk it -- but about how much of it arrives at once.
"""


def window_from_query(default_limit: int) -> Tuple[int, int]:
    """
    Read ``limit`` and ``offset`` from the query string, within bounds.

    A value that is not a number at all is the default: ``type=int``
    hands back the fallback rather than raising, which is the behaviour
    both listings already had.

    The ceiling is the module's and not the caller's. Only the default
    differs between the two listings -- fifty links, a hundred accounts --
    and how much of a table may arrive at once is a decision about the
    service rather than about either listing.

    Args:
        default_limit: Window size when the request names none.

    Returns:
        The limit and the offset, in that order.
    """
    limit = request.args.get("limit", default_limit, type=int)
    offset = request.args.get("offset", 0, type=int)
    return max(1, min(limit, MAX_PAGE_SIZE)), max(0, offset)
