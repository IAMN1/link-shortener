"""
Answering in the API's error envelope.

Every refusal the API makes carries ``error``, ``message`` and a timestamp
-- ``ErrorResponse`` -- and almost every one of them is built by the global
error handler out of the exception a view raised. A view that answers by
hand instead is answering in a different shape, and a client that reads
``error`` as a machine-readable code gets a sentence from those and a code
from the rest.

Raising is still the first choice: ``DomainError`` with the right code goes
through the handler, which decides the status from the code and logs the
refusal on the way past. This helper is for the few answers that cannot be
an exception -- ones that also set or clear cookies, and so need the
response object in hand.
"""

from typing import FrozenSet, Tuple

from flask import Response, jsonify, render_template, request

from link_shortener.web.schemas.error import ErrorResponse

CODES_OFFERING_LOOKUP: FrozenSet[str] = frozenset(
    {"LINK_NOT_FOUND", "LINK_EXPIRED"}
)
"""Refusals after which another short code is worth offering.

A code that leads nowhere is the ordinary business of a link shortener, so
``error.html`` puts a lookup form under those two and plain text under
everything else. Which refusals those are is decided here, by code, and not
in the page by reading the sentence: the sentence is translated, and
"Ссылка не найдена" does not contain the word ``link``.
"""


def error_response(code: str, message: str, status: int) -> Tuple[Response, int]:
    """
    Build a refusal in the same envelope the error handler produces.

    Args:
        code: Machine-readable code, e.g. ``UNAUTHENTICATED``. This is what
            ``error`` carries; it is not a sentence for a human.
        message: The sentence for a human.
        status: HTTP status to answer with.

    Returns:
        Tuple of ``(response, status)``, ready to return from a view. The
        response is handed back rather than the finished tuple alone so a
        caller can still set or clear cookies on it.
    """
    body = ErrorResponse(error=code, message=message).model_dump()
    return jsonify(body), status


def error_page(code: str, message: str, status: int) -> Tuple[str, int]:
    """
    Draw a refusal as a page, telling the page which refusal it is.

    The one door to ``error.html``. Rendering it by hand elsewhere works
    until the day a caller forgets ``code``, and what a missing code costs
    is silent: the page still draws, still says the right sentence, and the
    lookup form under a dead short code simply is not there any more.

    Args:
        code: Machine-readable code, the same one the API answers in
            ``error``. What the page branches on.
        message: The sentence for a human, already translated.
        status: HTTP status to answer with.

    Returns:
        Tuple of ``(rendered page, status)``, ready to return from a view
        or an error handler.
    """
    # The page is handed the decision, not the code to decide from. It has
    # no other use for the code, and a template that branches on a string
    # is a second place where the list of those codes lives.
    return render_template(
        "error.html",
        error=message,
        offers_lookup=code in CODES_OFFERING_LOOKUP,
    ), status


def wants_html() -> bool:
    """
    Say whether this request should be answered with a page.

    The rule the error handler has always used, lifted here so the
    throttle can follow it too. It did not: ``RateLimitMiddleware`` built
    its answer by hand and returned JSON wherever the request came from,
    so an exhausted limit on ``GET /login`` put a raw envelope in the
    browser while every other refusal on that same route rendered
    ``error.html``.

    The decision is the path and nothing else. ``Accept`` is deliberately
    not read: a browser sends ``text/html`` on an address-bar navigation,
    and a client that asked for JSON by URL should not be handed a page
    because of it.

    Returns:
        ``True`` when the request is for a page rather than for the API.
    """
    return not request.path.startswith("/api/")
