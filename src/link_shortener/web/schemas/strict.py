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

from typing import Any, Dict

from pydantic import BaseModel, ConfigDict

from link_shortener.domain.policies.password_policy import (
    MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH,
)
from link_shortener.domain.value_objects.email import EMAIL_PATTERN


class StrictRequest(BaseModel):
    """A request body that refuses what it does not declare.

    ``model_config`` is merged across inheritance in Pydantic v2, so a
    model deriving from this keeps its own ``json_schema_extra`` and
    whatever else it sets.
    """

    model_config = ConfigDict(extra="forbid")


AN_ADDRESS: Dict[str, Any] = {"format": "email", "pattern": EMAIL_PATTERN}
"""What the service means by an address, in the document's own words.

Put in the **schema** and not in the field's validation, and the
difference is the whole of it: these models are lenient readers by design
-- the rule lives in ``Email``, which is where every other way into this
service meets it -- and turning them into gates would answer a malformed
address with Pydantic's sentence instead of the domain's, on two routes
and not on the rest.

What it fixes is a document that did not say what it accepts. ``email``
was published as a plain string, so a client generated from it had no way
to know an address was wanted, and the contract run -- which builds
requests from the schema -- sent ``"invalid-url"`` to sign-in,
registration, the reset request and the resend, and got ``400`` from all
four. The service was right and the document was silent.

The pattern is the one ``Email`` matches with, imported rather than
copied: two spellings of one rule is how they start to disagree.

Here beside ``StrictRequest`` rather than in ``auth_requests``, because
the admin bodies say the same thing about the same fields and said it in
their own words: this docstring declares itself the single entry, and a
second copy of it was written one module over in the same change.
"""

A_PASSWORD: Dict[str, Any] = {
    "minLength": MIN_PASSWORD_LENGTH,
    "maxLength": MAX_PASSWORD_LENGTH,
}
"""The length a password has to be, from the policy that enforces it.

Length only. The policy also refuses passwords on a common-passwords list,
and a list is not a thing a JSON Schema can express -- so a document
saying "at least eight characters" is telling the truth and not the whole
of it, which is the best a schema can do here.
"""
