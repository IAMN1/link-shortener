"""
The API described in the form a machine can read.

``/api/docs`` used to render the landing page: the route existed, answered
200, and told nobody anything. What is served now is generated rather than
written twice -- every request and response body here is the same Pydantic
model the endpoint actually validates against, so a field that changes shape
changes shape in the document with it. What cannot be generated is the part
that lives in the routing table and the decorators: which paths exist, which
verbs they take, who may call them, and what each status means. That is
written out below, once, and a test holds it against the application's real
URL map so an endpoint added later is a failing test rather than an
undocumented one.

Two answers are not written out per operation but folded in over all of
them: the throttle's 429, which any route can give, and the CSRF layer's
403, which any state-changing one can. Five of the fifteen operations
declare the first and none declares the second, so a generated client had
no case for a refusal that arrives before any endpoint is reached. OpenAPI
3.x cannot state a response once for a document, so the alternative was
typing them into all fifteen by hand and watching the sixteenth be
forgotten.

No Swagger UI is bundled. It is a megabyte and a half of vendored assets or
a script tag pointing at somebody else's CDN, and neither belongs in a
service whose whole job is to be a small redirect. The document is served at
``/api/openapi.json`` for any tool that wants it -- Swagger UI, Redoc,
Postman, a client generator -- and ``/api/docs`` renders it as a page.
"""

from typing import Any, Dict, Optional

from link_shortener.web.schemas.batch import BatchCreateResponse
from link_shortener.web.schemas.error import ErrorResponse
from link_shortener.web.schemas.link import (
    ExtendedLinkInfoResponse, ShortLinkResponse
)
from link_shortener.web.schemas.requests import (
    BatchCreateLinkRequest, CreateShortLinkRequest
)
from link_shortener.web.schemas.auth import (
    MessageResponse, RefreshResponse, RegisterResponse, TokenPairResponse
)
from link_shortener.web.schemas.stats import (
    MyStatsResponse, ServiceStatsResponse
)


OPENAPI_VERSION = "3.1.0"

MODELS = {
    "CreateShortLinkRequest": CreateShortLinkRequest,
    "BatchCreateLinkRequest": BatchCreateLinkRequest,
    "ShortLinkResponse": ShortLinkResponse,
    "ExtendedLinkInfoResponse": ExtendedLinkInfoResponse,
    "BatchCreateResponse": BatchCreateResponse,
    "ServiceStatsResponse": ServiceStatsResponse,
    "MyStatsResponse": MyStatsResponse,
    "RegisterResponse": RegisterResponse,
    "TokenPairResponse": TokenPairResponse,
    "RefreshResponse": RefreshResponse,
    "MessageResponse": MessageResponse,
    "ErrorResponse": ErrorResponse,
}
"""Every schema the API speaks, taken from the models it validates with."""


def _ref(name: str) -> Dict[str, Any]:
    """Reference a component schema by name."""
    return {"$ref": f"#/components/schemas/{name}"}


def _json(name: str) -> Dict[str, Any]:
    """A JSON body of one schema."""
    return {"content": {"application/json": {"schema": _ref(name)}}}


def _error(description: str) -> Dict[str, Any]:
    """An error response, which is always the same shape."""
    return {"description": description, **_json("ErrorResponse")}


OPERATION_VERBS = (
    "get", "put", "post", "delete", "options", "head", "patch", "trace"
)
"""
The keys of a path item that are operations.

A path item may also carry ``summary``, ``description``, ``parameters``,
``servers`` and ``$ref``. Treating every key as an operation turned a
path-level ``parameters`` list -- the obvious place to lift the four
copies of ``CODE_PARAMETER`` to -- into a 500 from ``/api/openapi.json``.
"""

SAFE_VERBS = frozenset({"get", "head", "options", "trace"})
"""
Verbs the CSRF layer lets through without asking for a token.

A second spelling of ``csrf.SAFE_METHODS`` rather than an import: the
document describes the application and does not take part in it, and
``web.schemas`` importing from ``web.middleware`` would be the first edge
in that direction -- today every edge runs the other way. The price of the
second list is that it can drift, so a test holds the two equal.
"""

THROTTLE_REFUSAL = (
    "the throttle refused the request; Retry-After says when the window "
    "clears"
)

CSRF_REFUSAL = (
    "a cookie-authenticated write carrying no valid X-CSRF-Token"
)

def _throttle_headers() -> Dict[str, Any]:
    """
    Build the headers a refusal from the throttle carries.

    Built per call, not shared. One dict handed to fifteen operations is
    one dict: editing the wording in a single operation would edit it
    everywhere, and this document is rebuilt on every request to
    ``/api/openapi.json``.

    Returns:
        The header objects, freshly made.
    """
    # Retry-After alone. The throttle's own refusal also carries
    # X-RateLimit-Limit and X-RateLimit-Remaining, but a 429 from the guest
    # quota does not -- the response hook deliberately leaves somebody
    # else's refusal alone rather than stamping counters that contradict
    # its body. Declaring them here would promise, on two operations, what
    # the code goes out of its way not to send.
    return {
        "Retry-After": {
            "description": "Seconds until the window clears.",
            "schema": {"type": "integer"},
        },
    }


def _merge_response(
    existing: Optional[Dict[str, Any]], reason: str
) -> Dict[str, Any]:
    """
    Add a reason to a declared response without rebuilding it.

    Rebuilding it through ``_error`` dropped whatever else the response
    carried -- headers, a content type that was not JSON -- and read as a
    description-only object because today every response here happens to
    be one.

    A response written as a ``$ref`` is left exactly as it is. In OpenAPI
    3.0 a sibling of ``$ref`` is ignored, so folding a reason in beside it
    would drop that reason silently rather than loudly.

    Args:
        existing: The response object already declared, if any.
        reason: The reason to fold into its description.

    Returns:
        The response object to declare.
    """
    sentence = reason[0].upper() + reason[1:]

    if existing is None:
        return _error(sentence)

    if "$ref" in existing:
        return existing

    described = existing.get("description")
    if not described:
        return {**existing, "description": sentence}

    # Idempotent: the document is rebuilt per request, and folding the same
    # reason in twice reads as a stutter rather than as a bug.
    if reason in described:
        return dict(existing)

    return {**existing, "description": f"{described}; or {reason}"}


def _add_cross_cutting_responses(paths: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fold in the answers every operation can give and few of them declared.

    Two layers sit in front of the whole application and were barely
    mentioned here: the throttle can answer 429 to any request, and five
    of the fifteen operations say so; the CSRF layer answers 403 to any
    cookie-authenticated write, and none did. A client generated from the
    document had no case for the second at all.

    Written here rather than typed into each operation because OpenAPI 3.x
    has no way to state a response once for a document. The request for
    one (OAI/OpenAPI-Specification#521) stood from 2015 until it was closed
    in 2024, deferred to a future version; for 3.x the answer is still "put
    a $ref in every operation". Typing that out is exactly how a document
    falls behind the code it describes, which is the failure this module
    exists to avoid.

    Both reasons are merged into whatever the operation already declares,
    never substituted for it: an operation that answers 429 for a quota of
    its own answers it for the throttle too, and a reader has to be told
    which refusal they are looking at.

    Args:
        paths: The hand-written path table.

    Returns:
        A copy of it, every operation written out inline carrying the
        throttle's refusal and every state-changing one carrying the CSRF
        layer's. A path item that is itself a ``$ref`` is passed through:
        its operations live elsewhere and are not this function's to edit.
    """
    described: Dict[str, Any] = {}

    for path, operations in paths.items():
        described[path] = {}
        for key, value in operations.items():
            if key.lower() not in OPERATION_VERBS:
                described[path][key] = value
                continue

            responses = dict(value.get("responses", {}))

            if key.lower() not in SAFE_VERBS:
                responses["403"] = _merge_response(
                    responses.get("403"), CSRF_REFUSAL
                )

            refusal = _merge_response(responses.get("429"), THROTTLE_REFUSAL)
            # Merged, not setdefault: an operation whose 429 already names
            # one header would otherwise be the one left without the rest.
            refusal["headers"] = {
                **_throttle_headers(), **refusal.get("headers", {})
            }
            responses["429"] = refusal

            # Sorted, not insertion-ordered. The page renders them in the
            # order it finds them and jsonify sorts, so appending a refusal
            # showed 403 after 429 on the page and before it in the JSON --
            # the same document disagreeing with itself about itself.
            described[path][key] = {
                **value, "responses": dict(sorted(responses.items()))
            }

    return described


CODE_PARAMETER = {
    "name": "short_code",
    "in": "path",
    "required": True,
    "description": "The short code, 6-10 of A-Z a-z 0-9 _ -",
    "schema": {"type": "string"},
}

PATHS: Dict[str, Any] = {
    "/api/v1/shorten": {
        "post": {
            "summary": "Shorten a URL",
            "description": (
                "Anonymous callers may shorten links through the 'guest' "
                "role and are bounded by the guest quota; their links carry "
                "a deletion token, returned here and nowhere else, because "
                "a link with no owner has nothing for ownership to match. "
                "Answers 200 rather than 201 when the caller already has a "
                "live link for this URL."
            ),
            "tags": ["links"],
            "requestBody": {"required": True, **_json("CreateShortLinkRequest")},
            "responses": {
                "201": {"description": "Created", **_json("ShortLinkResponse")},
                "200": {
                    "description": "The caller's existing link for this URL",
                    **_json("ShortLinkResponse"),
                },
                "400": _error("Malformed body, URL, or ttl_seconds"),
                "401": _error("The 'guest' role does not carry link:create"),
                "415": _error("A body that is not declared application/json"),
                "429": _error("Guest quota spent"),
            },
        }
    },
    "/api/v1/batch/shorten": {
        "post": {
            "summary": "Shorten several URLs at once",
            "description": (
                "Reports per item: what could be created is created, and "
                "what could not comes back as an item error with a 200. "
                "The quota answers 429 only when it refused every single "
                "item, which is the same refusal the single endpoint "
                "answers 429 to; the throttle answers 429 to the request "
                "as a whole, before any item is looked at."
            ),
            "tags": ["links"],
            "requestBody": {"required": True, **_json("BatchCreateLinkRequest")},
            "responses": {
                "200": {"description": "Per-item results", **_json("BatchCreateResponse")},
                "400": _error("Malformed body, or more URLs than the limit"),
                "401": _error("The 'guest' role does not carry link:create"),
                "415": _error("A body that is not declared application/json"),
                "429": _error("Guest quota spent, and no item got through"),
            },
        }
    },
    "/api/v1/links/{short_code}": {
        "get": {
            "summary": "Look up a link",
            "description": (
                "Public. The owner's identifier and the click counters are "
                "withheld from everyone but the link's owner, an admin, and "
                "a holder of stats:view_any -- the fields are present and "
                "null rather than absent, so 'withheld' and 'older build' "
                "are not the same thing on the wire."
            ),
            "tags": ["links"],
            "parameters": [CODE_PARAMETER],
            "responses": {
                "200": {"description": "The link", **_json("ShortLinkResponse")},
                "404": _error("No link carries that code"),
                "410": _error("The link has expired"),
            },
        },
        "delete": {
            "summary": "Delete a link",
            "description": (
                "The link's owner needs link:delete_own, anybody else needs "
                "link:delete_any, and the holder of a guest link's deletion "
                "token needs neither -- it names that one row. Decided "
                "against the stored row, in the transaction that deletes it."
            ),
            "tags": ["links"],
            "parameters": [
                CODE_PARAMETER,
                {
                    "name": "X-Deletion-Token",
                    "in": "header",
                    "required": False,
                    "description": (
                        "The token returned when a link was created without "
                        "an account"
                    ),
                    "schema": {"type": "string"},
                },
            ],
            "responses": {
                "200": {"description": "Deleted", **_json("MessageResponse")},
                "401": _error("Neither an account nor a valid token"),
                "403": _error("Not this caller's link to delete"),
                "404": _error("No link carries that code"),
            },
        },
    },
    "/api/v1/links/{short_code}/extended": {
        "get": {
            "summary": "Look up a link with its derived metrics",
            "description": (
                "Restricted to the same three the counters are shown to, and "
                "not by coincidence: every field here is computed from them."
            ),
            "tags": ["links"],
            "parameters": [CODE_PARAMETER],
            "responses": {
                "200": {"description": "The link", **_json("ExtendedLinkInfoResponse")},
                "401": _error("Nobody authenticated this request"),
                "403": _error("Not entitled to this link's traffic"),
                "404": _error("No link carries that code"),
                "410": _error("The link has expired"),
            },
        }
    },
    "/api/v1/links/mine": {
        "get": {
            "summary": "List the caller's links",
            "tags": ["links"],
            "security": [{"bearerAuth": []}],
            "responses": {
                "200": {
                    "description": "The caller's links",
                    "content": {"application/json": {"schema": {
                        "type": "array", "items": _ref("ShortLinkResponse")
                    }}},
                },
                "401": _error("Authentication required"),
            },
        }
    },
    "/api/v1/stats": {
        "get": {
            "summary": "Service-wide statistics",
            "description": (
                "Open to anonymous callers: the seeded guest role carries "
                "stats:view_basic. The popular-links breakdown "
                "additionally needs stats:view_full and comes back empty "
                "without it."
            ),
            "tags": ["stats"],
            # No 401, alone among the endpoints here. The guest role holds
            # stats:view_basic and the anonymous ceiling allows it, so
            # there is no request this endpoint could answer with one --
            # the live run asserts the anonymous 200. It was declared
            # anyway, and a declared status that cannot happen is read as
            # "this is protected". Owner's decision 2026-08-09: the
            # totals stay public and the document follows the code.
            "responses": {
                "200": {"description": "Totals", **_json("ServiceStatsResponse")},
                "403": _error("Not entitled to the statistics"),
            },
        }
    },
    "/api/v1/stats/mine": {
        "get": {
            "summary": "The caller's own statistics",
            "tags": ["stats"],
            "security": [{"bearerAuth": []}],
            "responses": {
                "200": {
                    "description": "Totals for this caller",
                    **_json("MyStatsResponse"),
                },
                "401": _error("Authentication required"),
            },
        }
    },
    "/api/v1/auth/register": {
        "post": {
            "summary": "Create an account",
            "description": (
                "The password must be at least 8 characters and must not be "
                "one attackers already have. No composition rules. "
                "Answers 202 whether or not the address was already "
                "registered, and returns no account details either way -- "
                "telling the two apart would say who is registered. The "
                "address is mailed in both cases: a confirmation link if it "
                "was free, a notice that an account exists if it was not."
            ),
            "tags": ["auth"],
            "responses": {
                "202": {"description": "Accepted", **_json("RegisterResponse")},
                "400": _error("Malformed body, or a password the policy refuses"),
                "429": _error("Too many registrations from this address"),
            },
        }
    },
    "/api/v1/auth/login": {
        "post": {
            "summary": "Exchange credentials for tokens",
            "description": (
                "The access token comes back in the body; the refresh token "
                "is set as an HttpOnly cookie and also returned for clients "
                "with no cookie jar."
            ),
            "tags": ["auth"],
            "responses": {
                "200": {"description": "Tokens", **_json("TokenPairResponse")},
                "400": _error("Malformed body or malformed email"),
                "401": _error(
                    "Wrong credentials, an inactive account, or an address "
                    "nobody has confirmed (EMAIL_NOT_VERIFIED)"
                ),
                "429": _error("Too many attempts from this address"),
            },
        }
    },
    "/api/v1/auth/verify": {
        "get": {
            "summary": "Confirm an email address",
            "description": (
                "Opened from the link in the confirmation message. Answers "
                "the same whether the token is unknown, already spent, "
                "expired, or names an account that no longer exists -- "
                "telling them apart would say who is registered."
            ),
            "tags": ["auth"],
            "parameters": [
                {
                    "name": "token",
                    "in": "query",
                    "required": True,
                    "schema": {"type": "string"},
                    "description": "The token from the confirmation link.",
                }
            ],
            "responses": {
                "200": {
                    "description": "The address is confirmed",
                    **_json("MessageResponse"),
                },
                "400": _error("The link is not usable"),
            },
        }
    },
    "/api/v1/auth/resend-verification": {
        "post": {
            "summary": "Ask for another confirmation message",
            "description": (
                "Answers 202 whether or not the address is registered and "
                "whether or not it is already confirmed. Issuing a new "
                "token retires the ones outstanding."
            ),
            "tags": ["auth"],
            "responses": {
                "202": {
                    "description": "Accepted, whatever was found",
                    **_json("MessageResponse"),
                },
                "400": _error("Malformed body or malformed email"),
                "429": _error("Too many requests from this address"),
            },
        }
    },
    "/api/v1/auth/refresh": {
        "post": {
            "summary": "Rotate the refresh token",
            "tags": ["auth"],
            "responses": {
                "200": {"description": "A new pair", **_json("RefreshResponse")},
                "401": _error("No usable refresh token"),
            },
        }
    },
    "/api/v1/auth/logout": {
        "post": {
            "summary": "End the session",
            "tags": ["auth"],
            "responses": {
                "200": {"description": "Ended", **_json("MessageResponse")}
            },
        }
    },
    "/{short_code}": {
        "get": {
            "summary": "Follow a short link",
            "description": (
                "The redirect itself. A code that cannot exist and a code "
                "nobody has taken are the same answer: 404."
            ),
            "tags": ["links"],
            "parameters": [CODE_PARAMETER],
            "responses": {
                "302": {"description": "Redirect to the original URL"},
                "404": _error("No link carries that code"),
                "410": _error("The link has expired"),
            },
        }
    },
}
"""What the routing table and the decorators know, written out once."""


def build_openapi(base_url: str, version: str = "1.0.0") -> Dict[str, Any]:
    """
    Assemble the OpenAPI document.

    Args:
        base_url: Public base URL of this deployment.
        version: Version to report for the API.

    Returns:
        The document, ready to be serialized as JSON.
    """
    schemas: Dict[str, Any] = {}
    for name, model in MODELS.items():
        schema = model.model_json_schema(
            ref_template="#/components/schemas/{model}"
        )
        # Pydantic hangs nested models off $defs; OpenAPI wants them beside
        # their parents in components.
        schemas.update(schema.pop("$defs", {}))
        schemas[name] = schema

    return {
        "openapi": OPENAPI_VERSION,
        "info": {
            "title": "Link Shortener API",
            "version": version,
            "description": (
                "A URL shortener. Anonymous callers may shorten links "
                "within a quota; accounts get ownership, listing and "
                "statistics.\n\n"
                "Every state-changing operation can answer 403 from the "
                "CSRF layer, before the endpoint is reached. It applies "
                "only to requests that authenticate by cookie: a client "
                "presenting a valid Authorization: Bearer token is not "
                "asked for a token, because it has already shown it can "
                "set request headers.\n\n"
                "Two operations are the exception and are guarded whatever "
                "the headers say: POST /api/v1/auth/refresh and POST "
                "/api/v1/auth/logout read the session cookie themselves, "
                "so their authority comes from the cookie and a Bearer "
                "header buys no exemption."
            ),
        },
        "servers": [{"url": base_url.rstrip("/")}],
        "tags": [
            {"name": "links", "description": "Creating, reading and deleting links"},
            {"name": "stats", "description": "Counters"},
            {"name": "auth", "description": "Accounts and tokens"},
        ],
        "paths": _add_cross_cutting_responses(PATHS),
        "components": {
            "schemas": schemas,
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "JWT",
                }
            },
        },
    }
