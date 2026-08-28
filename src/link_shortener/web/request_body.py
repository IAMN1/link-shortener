"""
Reading what a request carries in its body.

The other half of ``web/responses.py``: one module decides how an answer is
shaped, this one decides how a body is read, and both exist so that the
decision is made once rather than per controller.

It was made twice. ``ApiController`` and ``AuthController`` each grew a
private reader, and the two disagreed about the same body -- which is a
disagreement a caller sees. Ten thousand nested brackets exhaust the
JSON decoder's stack, and ``RecursionError`` is not a ``ValueError``, so
Werkzeug does not turn it into 400 and it reaches the catch-all as a 500.
Both readers close that. Only one of them then says what happened: the
API's answers "Request body is nested too deeply", while the auth routes
treated the whole body as absent and answered "Email and password are
required" -- telling somebody to fill in fields they had already filled
in. The API's own docstring recorded the split while it lasted: "The same
hole was closed for the auth controller in its own block and left open
here."

Silent parsing is likewise gone from the auth routes. ``get_json(silent=
True)`` swallows a body Flask would otherwise refuse outright, so a form
submission to ``/api/v1/auth/login`` came back 400 "Email and password are
required" where every other endpoint answers 415 "The service expects a
JSON body". The fields were there; the encoding was not.
"""

from flask import request

from link_shortener.domain import ValidationError
from link_shortener.domain.i18n import N_


def decoded_body():
    """
    Decode the request body, refusing one the decoder cannot get through.

    Returns:
        The decoded body -- of whatever JSON type it happens to be -- or
        ``None`` when the request carries none.

    Raises:
        ValidationError: If the body is nested too deeply to decode.
        HTTPException: Flask's own, for a body that is not JSON at all
            (400) or is not offered as JSON (415). Those are left to it
            deliberately: they are the same refusals it makes everywhere
            else, and the error handler already words both.
    """
    try:
        return request.get_json(silent=False)
    except RecursionError:
        # ``"[" * 10000`` nests ten thousand deep and decodes
        # recursively, so the decoder runs out of stack. Werkzeug turns a ``ValueError``
        # from the decoder into 400 and a ``RecursionError`` is not one, so
        # it went past every handler into the catch-all: 500, from an
        # unauthenticated request, on every endpoint that reads a body.
        raise ValidationError(
            N_("Request body is nested too deeply"), field="body"
        )


def json_object() -> dict:
    """
    Read the request body as a JSON object.

    Guards the *shape* of the body, which the request schemas cannot: they
    are handed the body as keyword arguments, and ``**`` on anything but a
    mapping raises ``TypeError`` before Pydantic is reached. A body of
    ``[1, 2]``, ``"text"``, ``5`` or ``true`` therefore answered 500, on
    both creation endpoints, without authentication.

    Returns:
        The decoded object, or an empty one when the body is absent, so
        that a missing field is reported as the missing field it is.

    Raises:
        ValidationError: If the body is not a JSON object, or is nested
            too deeply to decode.
    """
    data = decoded_body()

    if data is None:
        return {}

    if not isinstance(data, dict):
        raise ValidationError(
            N_("Request body must be a JSON object"), field="body"
        )

    return data


def optional_json_object() -> dict:
    """
    Read the body as an object on a route that does not require one.

    ``/auth/logout`` and ``/auth/refresh`` take their token from the
    cookie and fall back to the body only for a client that keeps no
    cookie jar. A request with no body at all is ordinary there rather
    than wrong, and read strictly it is refused twice over: Flask answers
    415 to a body that is not *offered* as JSON, and 400 to one that is
    offered and empty.

    Both halves are needed, and the second is the one that bites. This
    application's own pages sign out through ``apiFetch``, which sets
    ``Content-Type: application/json`` on every request it makes and
    sends no body with a sign-out -- so the header says JSON, the body is
    nought bytes, and a strict read calls that malformed. Measured
    against the running stack: ``POST /api/v1/auth/logout`` came back 400
    "Malformed request body". It is masked in a browser, because a
    browser has the cookie and never reaches this line, and that is
    exactly what makes it worth closing rather than leaving.

    A body with something in it is still read strictly: malformed is
    malformed wherever it arrives.

    Returns:
        The decoded object, or an empty one when no JSON body was sent.

    Raises:
        ValidationError: If a JSON body was sent and is not an object, or
            is nested too deeply to decode.
    """
    # ``get_data`` rather than ``content_length``, which is ``None`` for a
    # chunked request and would read as "empty" for a body that is not.
    # Flask caches what it reads, so the decode below sees the same bytes.
    if not request.is_json or not request.get_data(cache=True):
        return {}

    return json_object()
