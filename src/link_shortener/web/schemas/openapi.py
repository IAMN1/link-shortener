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

No Swagger UI is bundled. It is a megabyte and a half of vendored assets or
a script tag pointing at somebody else's CDN, and neither belongs in a
service whose whole job is to be a small redirect. The document is served at
``/api/openapi.json`` for any tool that wants it -- Swagger UI, Redoc,
Postman, a client generator -- and ``/api/docs`` renders it as a page.
"""

from typing import Any, Dict

from link_shortener.web.schemas.batch import BatchCreateResponse
from link_shortener.web.schemas.error import ErrorResponse
from link_shortener.web.schemas.link import (
    ExtendedLinkInfoResponse, ShortLinkResponse
)
from link_shortener.web.schemas.requests import (
    BatchCreateLinkRequest, CreateShortLinkRequest
)
from link_shortener.web.schemas.stats import ServiceStatsResponse


OPENAPI_VERSION = "3.0.3"

MODELS = {
    "CreateShortLinkRequest": CreateShortLinkRequest,
    "BatchCreateLinkRequest": BatchCreateLinkRequest,
    "ShortLinkResponse": ShortLinkResponse,
    "ExtendedLinkInfoResponse": ExtendedLinkInfoResponse,
    "BatchCreateResponse": BatchCreateResponse,
    "ServiceStatsResponse": ServiceStatsResponse,
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
                "409": _error("The chosen short code is already taken"),
                "429": _error(
                    "Guest quota spent. Retry-After says when the window "
                    "clears; a throttle refusal says the same in seconds."
                ),
            },
        }
    },
    "/api/v1/batch/shorten": {
        "post": {
            "summary": "Shorten several URLs at once",
            "description": (
                "Reports per item: what could be created is created, and "
                "what could not comes back as an item error with a 200. "
                "Answers 429 only when the quota refused every single item, "
                "which is the same refusal the single endpoint answers 429 "
                "to."
            ),
            "tags": ["links"],
            "requestBody": {"required": True, **_json("BatchCreateLinkRequest")},
            "responses": {
                "200": {"description": "Per-item results", **_json("BatchCreateResponse")},
                "400": _error("Malformed body, or more URLs than the limit"),
                "401": _error("The 'guest' role does not carry link:create"),
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
                "200": {"description": "Deleted"},
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
                "200": {"description": "The caller's links"},
                "401": _error("Authentication required"),
            },
        }
    },
    "/api/v1/stats": {
        "get": {
            "summary": "Service-wide statistics",
            "description": (
                "Needs stats:view_basic; the popular-links breakdown "
                "additionally needs stats:view_full and comes back empty "
                "without it."
            ),
            "tags": ["stats"],
            "responses": {
                "200": {"description": "Totals", **_json("ServiceStatsResponse")},
                "401": _error("Authentication required"),
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
                "200": {"description": "Totals for this caller"},
                "401": _error("Authentication required"),
            },
        }
    },
    "/api/v1/auth/register": {
        "post": {
            "summary": "Create an account",
            "description": (
                "The password must be at least 8 characters and must not be "
                "one attackers already have. No composition rules."
            ),
            "tags": ["auth"],
            "responses": {
                "201": {"description": "Registered"},
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
                "200": {"description": "Tokens"},
                "400": _error("Malformed body or malformed email"),
                "401": _error("Wrong credentials, or the account is inactive"),
                "429": _error("Too many attempts from this address"),
            },
        }
    },
    "/api/v1/auth/refresh": {
        "post": {
            "summary": "Rotate the refresh token",
            "tags": ["auth"],
            "responses": {
                "200": {"description": "A new pair"},
                "401": _error("No usable refresh token"),
            },
        }
    },
    "/api/v1/auth/logout": {
        "post": {
            "summary": "End the session",
            "tags": ["auth"],
            "responses": {"200": {"description": "Ended"}},
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
                "statistics."
            ),
        },
        "servers": [{"url": base_url.rstrip("/")}],
        "tags": [
            {"name": "links", "description": "Creating, reading and deleting links"},
            {"name": "stats", "description": "Counters"},
            {"name": "auth", "description": "Accounts and tokens"},
        ],
        "paths": PATHS,
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
