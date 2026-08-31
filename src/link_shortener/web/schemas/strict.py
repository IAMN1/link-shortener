"""The base every request body is validated against.

Pydantic ignores a field it does not declare. For a response model that is
right -- extra keys are the caller's business. For a request body it means
the service accepts a field, answers `201`, and does nothing with it, which
is the one answer a caller cannot tell from success.

Measured on three separate live walks of this service: `POST
/api/v1/shorten` with `{"url": ..., "custom_code": "mycode1"}` answered
`201` with a generated code every time, and repeating the call with the
same `custom_code` produced another generated code. There is no custom
code in the HTTP API -- it exists only on `flask link create --code` --
and a caller asking for one had no way to learn they had not been given
it. The same silence covered a mistyped name: `?short_code=` where the
parameter is `code` answered `200` with service-wide figures instead of
one link's.

So a body is now refused when it carries a field this service does not
declare, with `422` and the field named. That is a narrower contract than
Pydantic's default and a deliberate one: this service would rather refuse
a request it does not understand than answer `201` to it.

Responses are not built on this. Nothing is validating them on the way
out, and forbidding extras there would only make a future field a crash.

One request body is deliberately left lenient: ``RefreshTokenRequest``.
It is the only optional body in the document -- a browser reaches
``/auth/refresh`` and ``/auth/logout`` with none, its token being in the
cookie -- and both routes build it from whatever arrived. Strict, a stray
field in a logout body refuses the logout, which is a security action
blocked over a field the route did not need. The reason is written at the
class as well, where somebody changing it will be standing.
"""

from pydantic import BaseModel, ConfigDict


class StrictRequest(BaseModel):
    """A request body that refuses what it does not declare.

    ``model_config`` is merged across inheritance in Pydantic v2, so a
    model deriving from this keeps its own ``json_schema_extra`` and
    whatever else it sets.
    """

    model_config = ConfigDict(extra="forbid")
