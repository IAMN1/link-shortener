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
it.

So a body is now refused when it carries a field this service does not
declare, with `400` and the field named -- `400` because that is what
`VALIDATION_ERROR` maps to in `error_handler.py`, and because `422` is on
the list of statuses this service does not answer with at all (Decisions,
"a refusal Werkzeug words itself keeps its English"). That is a narrower
contract than Pydantic's default and a deliberate one: this service would
rather refuse a request it does not understand than answer `201` to it.

The same silence used to cover a mistyped name on the **query string**:
`?short_code=` where the parameter is `code` answered `200` with
service-wide figures instead of one link's -- measured on a live stack,
`GET /api/v1/stats/visits?short_code=<code>` returning the whole
service's counts, byte for byte the same answer as asking with no
parameter at all. A model here guards a body, and nothing read
`request.args` through one.

That half is closed by `middleware/query_strictness.py`, which reads the
published OpenAPI document -- already the place each operation's
parameters are declared -- and refuses a name no operation of that path
declares. Under `/api/v1` only: a page is reached by navigation and
carries whatever the address bar was given.

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
