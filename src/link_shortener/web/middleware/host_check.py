"""
The names this service answers to.

Flask serves whatever ``Host`` it is given. That is the right default for
a framework and the wrong one for a deployment: a name pointed at this
address is answered exactly as the configured one is, and nothing in the
answer says the caller asked for something else.

Today that costs little here -- ``request.host`` is not read anywhere in
this application, and ``short_url`` comes from ``BASE_URL``, which is
configuration rather than the request. The reason to shut the door now is
that it is cheap while that stays true, and stops being cheap the first
time something builds an address from the request: a password-reset link
or a cache key made from an attacker's ``Host`` is the shape of the bug
this prevents, and it is a one-line change away in a file that knows
nothing about this one.

Off unless ``ALLOWED_HOSTS`` names something, and then the hook is not
even registered -- see ``ALLOWED_HOSTS`` in the base configuration for why
the default is empty rather than ``[DOMAIN]``.
"""

from typing import Iterable, List, Optional
from urllib.parse import urlsplit

from flask import Flask, abort, request

from link_shortener.application.ports.logger.logger import Logger


def normalise_host(value: Optional[str]) -> str:
    """
    Reduce a host to the form two of them are compared in.

    Strips the port, lowers the case and drops a trailing dot, so that
    ``Example.COM:8080`` and ``example.com.`` are one name. Accepts a
    value carrying a scheme as well, because a setting is as likely to be
    pasted from a browser's address bar as typed.

    Args:
        value: A ``Host`` header, or an entry from ``ALLOWED_HOSTS``.

    Returns:
        The bare lower-case host name, or ``""`` when there is none.
    """
    if not value:
        return ""

    candidate = value.strip()
    if not candidate:
        return ""

    # `urlsplit` finds the host only in something shaped like an address.
    # A bare `example.com:8080` parses as scheme `example.com`, so the
    # `//` is prefixed unless the value already carries a scheme -- and
    # then `hostname` does the work, brackets around an IPv6 literal
    # included.
    if "//" not in candidate:
        candidate = "//" + candidate

    try:
        host = urlsplit(candidate).hostname or ""
    except ValueError:
        # A malformed authority -- an unclosed bracket, a port that is not
        # a number. Not a name this service could be answering to, and the
        # caller learns that from the refusal rather than from a 500.
        return ""

    return host.rstrip(".").lower()


class HostCheckMiddleware:
    """
    Refuse a request whose ``Host`` this deployment does not claim.

    Registered after request logging and before authentication: a refused
    request still gets a ``request_id`` and a line in the journal, and it
    costs no database query.

    Attributes:
        allowed: Normalised host names this service answers to.
        logger: Where a refusal is recorded.
    """

    def __init__(self, app: Flask, logger: Logger):
        """
        Install the hook, unless there is nothing to check against.

        Args:
            app: The application to install into.
            logger: Logger for refusals.
        """
        self.logger = logger
        self.allowed: List[str] = self._normalise_all(
            app.config.get("ALLOWED_HOSTS") or []
        )

        # No list, no hook. An empty `ALLOWED_HOSTS` means "answer to
        # anything", and expressing that as a hook that always passes
        # would put a function call on every request to decide nothing.
        if self.allowed:
            app.before_request(self._check)

    @staticmethod
    def _normalise_all(values: Iterable[str]) -> List[str]:
        """
        Normalise the configured names, dropping the ones that say nothing.

        Args:
            values: Raw entries from ``ALLOWED_HOSTS``.

        Returns:
            The normalised names, without blanks and without duplicates,
            in the order they were given.
        """
        seen: List[str] = []
        for value in values:
            host = normalise_host(value)
            if host and host not in seen:
                seen.append(host)

        return seen

    def _check(self) -> None:
        """
        Compare the request's ``Host`` with the list, or refuse it.

        Raises:
            HTTPException: ``400`` when the name is not one of ours. The
                error handler turns it into the service's own envelope,
                which already carries a sentence for 400.
        """
        host = normalise_host(request.host)

        if host in self.allowed:
            return

        # The offending name is logged and not returned. A caller who sent
        # it knows what they sent; echoing it back into the body would
        # reflect an attacker-chosen string into a page, and the sentence
        # for 400 says enough.
        self.logger.warning(
            "Refused a request for a host this deployment does not claim",
            requested_host=host or request.host,
            allowed_hosts=self.allowed,
        )

        abort(400)
