import logging
import re
from urllib.parse import urlsplit, urlunsplit

from link_shortener.application.ports.journal_reader import (
    HEALTH_PROBE_EVENT_TYPE,
)

UTC_SECONDS = "%Y-%m-%dT%H:%M:%SZ"
"""How a machine-read journal states a moment, and the only way it may.

Not settable, and that is the point. ``JSONFormatter`` took the moment from
``datetime.fromtimestamp`` with no zone -- the machine's local one -- while
the structlog chain stamped UTC, so one instant was written 09:31:43 by one
configuration and 12:31:43 by the other, with nothing in either line to say
which. A reader could not tell them apart, and a filter by time meant
different things depending on ``LOGGER_TYPE``.

The format was read from ``LOG_DATE_FORMAT`` as well, so a deployment could
set it to anything and leave the file unparseable by whatever reads it
back. ``LOG_DATE_FORMAT`` shapes the console line instead, which is written
for a person -- in the standard chain, whose console has a formatter of its
own; the structlog chain renders its console over the one processor chain
it shares with the file, so there the two carry the same stamp. This one is
written for a program, and ISO 8601 in UTC is what a program can sort as
text and parse with ``fromisoformat``.

It lives in this module because three chains have to agree on it and this
is the one place all three can reach: ``json_formatter`` for the standard
journal, ``structlog_config`` for the other, and ``MinimalLogger``, which
writes the lines around a failure and is read beside both.
"""


def _standard_record_attrs() -> frozenset:
    """
    Return the attribute names every ``LogRecord`` carries by itself.

    Derived from a throwaway record rather than typed out, because the set
    grows between Python releases and a hand-written list silently falls
    behind. It did: 3.12 added ``taskName``, which neither formatter knew
    about, so every console line ended in ``[taskName=None]`` and every JSON
    line carried ``"taskName": null``.

    ``message`` and ``asctime`` are added by ``logging`` during formatting
    rather than at construction, so they are named explicitly.

    Returns:
        Names that belong to the logging machinery, not to the caller.
    """
    reference = logging.LogRecord(
        name="", level=logging.INFO, pathname="", lineno=0,
        msg="", args=(), exc_info=None,
    )
    return frozenset(reference.__dict__) | {"message", "asctime"}


STANDARD_RECORD_ATTRS = _standard_record_attrs()
"""Attributes a formatter must not mistake for application-supplied fields."""


def _without_userinfo(url: str) -> str:
    """
    Drop the credentials an address carries in front of its host.

    ``https://user:s3cret@example.com/x`` becomes
    ``https://***@example.com/x``: the value goes, the fact that there was
    one stays, because an audit trail that silently drops it cannot be
    told from one that never saw it -- and "this link was stored with a
    password in it" is exactly what an investigator needs to know.

    A URL without ``@`` in its authority is handed back as the very same
    string rather than reassembled. Reassembly is not free: ``urlsplit``
    followed by ``urlunsplit`` normalises -- the scheme is lower-cased, an
    empty ``#`` or ``?`` disappears -- and the audit trail should record
    what was submitted, not a tidied version of it. An address that did
    carry credentials is reassembled and therefore does get tidied; it is
    already not what was submitted, since the credentials are gone.

    Args:
        url: The address as it was given.

    Returns:
        The address without its userinfo component.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        # Not something urllib can take apart -- a malformed IPv6 literal,
        # say. Nothing can be removed safely from a string whose shape is
        # unknown, and guessing with a string operation could cut the URL
        # somewhere else entirely.
        return url

    if "@" not in parts.netloc:
        return url

    # The last "@" separates userinfo from host: RFC 3986 forbids a bare
    # "@" in the host, so anything before the final one is userinfo.
    host = parts.netloc.rsplit("@", 1)[1]
    return urlunsplit(parts._replace(netloc=f"***@{host}"))


_NESTED_USERINFO = re.compile(r"([a-zA-Z][a-zA-Z0-9+.\-]*://)[^/?#\s]+@")
"""An address carrying userinfo, wherever in the string it appears.

The host part is bounded by ``/?#`` rather than by ``@``: RFC 3986, 3.2
puts the authority "terminated by the next slash ("/"), question mark
("?"), or number sign ("#") character, or by the end of the URI", so an
``@`` reached before any of those is inside the authority -- which is the
only place userinfo can be. That is what keeps the pattern off
``/img@2x.png`` and ``?to=a@b.com``: their ``@`` follows a ``/`` or a
``?``, so no authority is still open. Greediness then takes the last
``@`` of the authority, for the same reason ``_without_userinfo`` does.

Whitespace bounds it too, which RFC 3986 does not say: a space cannot
appear unencoded in a URI at all, so a match spanning one would be
reading across two things rather than into one authority.
``_without_userinfo`` still masks that shape -- ``urlsplit`` keeps the
space inside the netloc -- so the narrower pattern costs no coverage.
"""


def _without_nested_userinfo(url: str) -> str:
    """
    Drop credentials from an address carried *inside* another address.

    ``urlsplit`` finds one authority -- the outer one -- so
    ``https://example.com/r?next=https://alice:s3cret@evil.example/``
    passes ``_without_userinfo`` untouched: its ``@`` sits in the query,
    not in the authority. Such a URL passes ``_validate_no_credentials``
    too, for the same reason, so it is not a shape the entry check keeps
    out -- it reaches the audit log by the ordinary path.

    Only addresses with a ``scheme://`` are matched. Credentials in a
    string that is not a URL at all (``user:pass@example.com/x``) are left
    alone: to enter storage a value must have an authority, so those
    shapes cannot be what a stored row holds, and matching them would cost
    false positives on ordinary text.

    Args:
        url: The address as it was given.

    Returns:
        The address with the userinfo of every embedded URL replaced.
    """
    return _NESTED_USERINFO.sub(r"\1***@", url)


def mask_url(url: str) -> str:
    """
    Make a URL safe to write down, and short enough to be worth writing.

    Two things happen, in this order. Credentials in front of the host are
    replaced with ``***``, which is what OWASP's Logging Cheat Sheet asks
    for; then the result is truncated.

    The order is the point: cutting first leaves the head of a long
    password verbatim, because past about 42 characters of userinfo the
    cut falls before the ``@`` and there is no authority left to clean.

    Credentials are taken from the address itself and from any address
    embedded in it. The two steps overlap rather than divide the work:
    the pattern reaches most outer authorities as well, and the parse
    reaches the two shapes it cannot -- a scheme-relative ``//`` address,
    and userinfo holding a space.

    What is not touched is a token in the query string. Removing those
    means keeping a list of parameter names, the list is never complete,
    and an address logged with a hole in the middle is harder to
    investigate than one logged whole. Nor is a bare ``user:pass@host``
    with no scheme: see ``_without_nested_userinfo``. Both gaps are
    written down in the developer guide.

    Args:
        url: The original URL.

    Returns:
        URL with credentials removed, truncated if it is still long.
    """
    url = _without_nested_userinfo(_without_userinfo(url))

    if len(url) > 100:
        return f"{url[:50]}...{url[-20:]}"
    return url


def mask_email(email: str) -> str:
    """
    Make an address safe to write into the audit journal.

    ``ivanov@example.com`` becomes ``i***@example.com``: the domain and the
    first character stay, the rest goes. What survives is enough for the
    questions the audit journal is read with -- whether repeated failures
    are landing on one account or spread across many, and whether the
    attempts name a domain that belongs here at all -- and not enough to be
    a list of this service's users.

    The full address is not lost to an investigator: ``application.log``
    records it whole on registration and on every sign-in, failed ones
    included. That journal is read under ``logs:view`` and this one under
    ``audit:view``, and masking here is what keeps the two permissions from
    being two routes to the same personal data. The audit journal is also
    the one that is kept longest -- ``maxsize 1G`` and ``rotate 200`` --
    which is the second reason not to fill it with addresses.

    A string with no ``@`` is masked whole rather than passed through. Such
    a value is not an address, and the only thing known about it is that
    something put it where an address belongs; ``***`` says that without
    guessing which part of it is safe.

    Args:
        email: The address as it was given.

    Returns:
        The address with its local part reduced to one character, or
        ``***`` if it does not look like an address at all.
    """
    if "@" not in email:
        return "***"

    # The last "@" separates the local part from the domain: a quoted local
    # part may contain one, a domain may not.
    local, domain = email.rsplit("@", 1)
    if not local:
        return f"***@{domain}"

    return f"{local[0]}***@{domain}"


HEALTH_PROBE_MESSAGE = "logging chain health probe"
"""What the four ``is_healthy`` implementations write.

One text, because the line lands in the journals an operator reads and has
to be recognisable there as the chain checking itself rather than as
something the service was asked to do.

It is written under ``HEALTH_PROBE_EVENT_TYPE`` as well, which is what
keeps it off the journals page unless somebody asks for it by name --
see that constant for the count that made it necessary.
"""

HEALTH_PROBE_FIELDS = {"event_type": HEALTH_PROBE_EVENT_TYPE}
"""The probe's own fields, in the shape both chains pass them.

A mapping rather than a keyword at four call sites: the standard chain
hands it to ``extra`` and the structlog chain expands it, and the two
would drift apart the first time one of them gained a second field.
"""


def probe_level(name: str) -> int:
    """
    Return the level a health probe has to be written at to be a probe.

    The four ``is_healthy`` implementations answer "can this chain still
    write" by writing, which is the only honest way to ask it. They wrote
    at ``DEBUG``, and a record is dropped on the first level test it fails:
    ``bootstrap`` gives every handler a level of its own -- the journal
    handlers ``LOG_LEVEL``, the audit handlers ``INFO`` unconditionally --
    so at the documented ``LOG_LEVEL=INFO`` the probe never reached a
    handler at all. Nothing raised, and the chain called itself healthy
    while its real records were being refused.

    Measured on the running stack, with the journal file replaced by a
    directory and four workers under load for two minutes: not one
    ``Demoting`` line, eight ``Upgrading`` lines -- four of them onto the
    implementation that was refusing every write. Every step down came
    from an exception in ``FailoverService.execute``, which is to say at
    the cost of the record that hit it.

    The logger's effective level, not the handlers'. It is the level this
    logger passes records at, so a probe written there travels exactly as
    far as a real record does. A handler stricter than its logger drops
    the probe -- and drops the real records of that level with it, so its
    state is not what the probe was asked about.

    Capped at ``WARNING``, and that cap is a limit worth stating. Above it
    the probe would be an ``ERROR`` or a ``CRITICAL`` record, which
    ``bootstrap`` routes to ``error.log`` -- a journal read as a list of
    things that went wrong, and one a monitor watches. A health check
    that files itself there every interval is worse than the failure it
    is looking for. ``LOG_LEVEL`` takes ``ERROR`` and ``CRITICAL``, and
    logging switched off sets the root to ``CRITICAL`` outright: measured
    before the cap, the suite printed five ``[critical] logging chain
    health probe`` lines.

    What the cap costs: a deployment whose journal drops everything below
    ``ERROR`` gets the old answer, ``True`` from a chain that may not be
    writing. Nothing there can be probed without writing into the error
    journal, and such a deployment has already given up the journal as
    something to watch. The way down through ``FailoverService.execute``
    still works -- at the cost of the record that finds it.

    Args:
        name: Logger name whose chain is being probed.

    Returns:
        The level to write the probe at: never below ``DEBUG`` -- an
        unset hierarchy answers ``0``, which is not a level anything is
        written at -- and never above ``WARNING``.
    """
    level = logging.getLogger(name).getEffectiveLevel()
    return min(max(level, logging.DEBUG), logging.WARNING)
