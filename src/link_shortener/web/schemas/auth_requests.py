"""
The bodies the authentication routes read, in the shape they read them.

Every other request body in this API is a Pydantic model the endpoint
validates against, and the document at ``/api/openapi.json`` is generated
from it. Nine operations were not: the auth routes read the body as a
dictionary, so the document named nine endpoints a generated client could
reach and not one it could fill in.

The models here close that and deliberately stop there. They state the
field names and their types -- what the wire carries -- and refuse nothing
else. The policy stays where it is: an address is the ``Email`` value
object's business and a password is ``password_policy``'s, and both refuse
with the offending field named. Restating either here would put a second
copy of a rule beside the first, which is the arrangement
``CreateUserRequest`` was taken out of and for the reason recorded there --
a copy disagrees silently.

Presence is not moved either, and that one is worth naming. A model
declaring ``email`` required answers a sign-in that carries no address the
way Pydantic answers everything: "Request validation failed", with the
field in ``details``, which is English by design and which no page renders
-- ``apiErrorText`` reads ``message`` and nothing else. The routes answer
"Email and password are required", translated, and that sentence is what
somebody looking at a form reads.

So a field is optional to the model and required in the schema. What the
model refuses is a type; what the route refuses is an absence; the document
states both, because a caller needs both and neither half is the other's.
"""

from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from link_shortener.web.schemas.strict import StrictRequest


def _body(
    required: List[str], example: Dict[str, Any]
) -> Callable[[Dict[str, Any]], None]:
    """
    Finish a body schema with what the model itself cannot say.

    Two things, and both because the models here are lenient readers rather
    than gates. ``required`` is the route's rule, enforced in the handler,
    and without it a document generated from optional fields would promise
    that a sign-in needs no address.

    The second is the leniency showing through. ``Optional[str]`` is how a
    reader says "the body need not carry this", and Pydantic publishes it
    as ``anyOf: [string, null]`` with ``default: null`` -- which in a
    contract reads as an invitation to send ``null``. It is not one: a
    route hands ``null`` to the same sentence it gives an absent field.
    What a caller may send is a string, and that is what the schema says.

    Args:
        required: Field names the route refuses the request without.
        example: A body the route accepts, for the rendered document.

    Returns:
        The callable ``json_schema_extra`` takes, which edits the generated
        schema in place.
    """
    def apply(schema: Dict[str, Any]) -> None:
        for prop in schema.get("properties", {}).values():
            variants = [
                variant for variant in prop.pop("anyOf", [])
                if variant != {"type": "null"}
            ]
            if len(variants) == 1:
                prop.update(variants[0])
            prop.pop("default", None)
        # Written only when there is something to write: an empty
        # ``required`` says the same as no ``required`` and reads as an
        # oversight rather than as the answer it is.
        if required:
            schema["required"] = required
        schema["example"] = example

    return apply


class CredentialsRequest(StrictRequest):
    """
    An address and a password: what ``/login`` and ``/register`` read.

    One model for both because it is one body. They differ in what they do
    with it and in what they answer, not in what they accept, and two
    names for one shape is how the two start to drift.
    """

    email: Optional[str] = Field(
        default=None, description="Address the account signs in with."
    )
    password: Optional[str] = Field(
        default=None, description="Its password.")

    model_config = ConfigDict(json_schema_extra=_body(
        required=["email", "password"],
        example={
            "email": "person@example.com",
            "password": "a-password-of-their-own",
        },
    ))


class EmailRequest(StrictRequest):
    """
    An address on its own: ``/resend-verification`` and ``/forgot-password``.

    Both answer 202 whatever the address turns out to be, so the body is
    the whole of what a caller controls here.
    """

    email: Optional[str] = Field(
        default=None, description="Address to send the message to."
    )

    model_config = ConfigDict(json_schema_extra=_body(
        required=["email"],
        example={"email": "person@example.com"},
    ))


class VerifyEmailRequest(StrictRequest):
    """
    The token out of a confirmation link, as the page sends it.

    The route also answers GET with the token in the query string, which is
    how a link mailed before that page existed still works. That spelling
    is a parameter in the document; this one is the body.
    """

    token: Optional[str] = Field(
        default=None, description="Token from the confirmation link."
    )

    model_config = ConfigDict(json_schema_extra=_body(
        required=["token"],
        example={"token": "a1b2c3d4e5f6"},
    ))


class ResetPasswordRequest(StrictRequest):
    """The token out of a reset link, and the password to set with it."""

    token: Optional[str] = Field(
        default=None, description="Token from the reset link.")
    new_password: Optional[str] = Field(
        default=None, description="Password to set on the account."
    )

    model_config = ConfigDict(json_schema_extra=_body(
        required=["token", "new_password"],
        example={
            "token": "a1b2c3d4e5f6",
            "new_password": "a-password-of-their-own",
        },
    ))


class ChangePasswordRequest(StrictRequest):
    """
    The password the caller has and the one they want.

    No account is named and none can be: the route changes the password of
    whoever the request is authenticated as. A field for an id here would
    be the whole authorization of the route, undone.
    """

    current_password: Optional[str] = Field(
        default=None, description="The password the account has now."
    )
    new_password: Optional[str] = Field(
        default=None, description="The password to replace it with."
    )

    model_config = ConfigDict(json_schema_extra=_body(
        required=["current_password", "new_password"],
        example={
            "current_password": "the-one-they-have",
            "new_password": "the-one-they-want",
        },
    ))


# Lenient, alone among the request bodies, and deliberately so. This one
# is optional -- every browser reaches `/auth/refresh` and `/auth/logout`
# with no body at all, because its token is in the HttpOnly cookie -- and
# both routes share `_read_refresh_token`, which builds it from whatever
# arrived. Made strict, a stray field in a logout body refuses the logout:
# a security action blocked over a field the route did not need. Measured:
# `POST /api/v1/auth/logout` answered 400 instead of ending the session.
class RefreshTokenRequest(BaseModel):
    """
    The refresh token, for a client that keeps no cookie jar.

    Required by neither ``/refresh`` nor ``/logout``, and this is the one
    body in this module where that is true rather than deferred: a browser
    holds the token in an HttpOnly cookie and sends no body at all. Hence
    an empty ``required`` -- the field is what a caller may send, not what
    the route asks for.
    """

    refresh_token: Optional[str] = Field(
        default=None,
        description=(
            "The refresh token issued at sign-in. Omit it when the request "
            "carries the refresh_token cookie."
        ),
    )

    model_config = ConfigDict(json_schema_extra=_body(
        required=[],
        example={"refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."},
    ))
