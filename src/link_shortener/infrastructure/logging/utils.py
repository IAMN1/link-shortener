import logging
import re
from urllib.parse import urlsplit, urlunsplit


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
    replaced with ``***``: "Use of the format \"user:password\" in the
    userinfo field is deprecated." (RFC 3986, 3.2.1), and OWASP's Logging
    Cheat Sheet lists authentication passwords among the data that "should
    usually not be recorded directly in the logs, but instead should be
    removed, masked, sanitized, hashed, or encrypted" -- which is what
    this is.

    The order is the point, and not merely for tidiness. Truncation alone
    was all this function used to do, and it left every short address
    whole -- ``user:pass@`` included, and secrets are short. Cutting first
    is worse than useless on a long one: past about 42 characters of
    userinfo the cut falls before the ``@``, so what follows has no
    authority left to clean and hands back the head of the credentials
    verbatim. Measured on a 60-character password: mask-then-cut removes
    it, cut-then-mask emits 37 of its characters.

    Credentials are taken from the address itself and from any address
    embedded in it. The two steps overlap rather than divide the work:
    the pattern reaches most outer authorities as well, and the parse
    reaches the two shapes it cannot -- a scheme-relative ``//`` address,
    and userinfo holding a space. Neither step alone is enough.

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
