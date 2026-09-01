"""
The API described in the form a machine can read.

What ``/api/docs`` serves is generated rather than written twice -- every
request and response body here is the same Pydantic model the endpoint
actually validates against, so a field that changes shape changes shape in
the document with it. What cannot be generated is the part
that lives in the routing table and the decorators: which paths exist, which
verbs they take, who may call them, and what each status means. That is
written out below, once, and a test holds it against the application's real
URL map so an endpoint added later is a failing test rather than an
undocumented one.

Two answers are not written out per operation but folded in over all of
them: the throttle's 429, which any route can give, and the CSRF layer's
403, which any state-changing one can. Some operations declare the first
and none declares the second, so a generated client had no case for a
refusal that arrives before any endpoint is reached. OpenAPI 3.x cannot
state a response once for a document, so the alternative was typing them
into every operation by hand and watching the next one added be
forgotten.

No Swagger UI is bundled. It is a megabyte and a half of vendored assets or
a script tag pointing at somebody else's CDN, and neither belongs in a
service whose whole job is to be a small redirect. The document is served at
``/api/openapi.json`` for any tool that wants it -- Swagger UI, Redoc,
Postman, a client generator -- and ``/api/docs`` renders it as a page.
"""

import re
from functools import lru_cache
from typing import Any, Dict, Optional, Type

from pydantic import BaseModel

from link_shortener.web.paging import MAX_PAGE_SIZE
from link_shortener.web.schemas.batch import BatchCreateResponse
from link_shortener.web.schemas.error import ErrorResponse
from link_shortener.web.schemas.security import SecurityCountsResponse
from link_shortener.web.schemas.journal import (
    DEFAULT_LINES, HARD_LIMIT, JournalPageResponse,
)
from link_shortener.web.schemas.link import (
    ExtendedLinkInfoResponse, ShortLinkResponse
)
from link_shortener.web.schemas.requests import (
    BatchCreateLinkRequest, CreateShortLinkRequest
)
from link_shortener.web.schemas.auth import (
    MessageResponse, RefreshResponse, RegisterResponse, TokenPairResponse
)
from link_shortener.web.schemas.auth_requests import (
    ChangePasswordRequest, CredentialsRequest, EmailRequest,
    RefreshTokenRequest, ResetPasswordRequest, VerifyEmailRequest,
)
from link_shortener.web.schemas.stats import (
    MyStatsResponse, ServiceStatsResponse
)
from link_shortener.web.schemas.visit_stats import (
    DailyVisitsResponse, VisitStatsResponse
)
from link_shortener.web.schemas.admin.admin_request import (
    CreateRoleRequest, CreateUserRequest, UpdateRolePermissionsRequest,
    UpdateUserRolesRequest
)
from link_shortener.web.schemas.admin.admin_responses import (
    RoleResponseSchema, UserResponseSchema
)


OPENAPI_VERSION = "3.1.0"

MODELS: Dict[str, Type[BaseModel]] = {
    "CreateShortLinkRequest": CreateShortLinkRequest,
    "BatchCreateLinkRequest": BatchCreateLinkRequest,
    "ShortLinkResponse": ShortLinkResponse,
    "ExtendedLinkInfoResponse": ExtendedLinkInfoResponse,
    "BatchCreateResponse": BatchCreateResponse,
    "ServiceStatsResponse": ServiceStatsResponse,
    "MyStatsResponse": MyStatsResponse,
    "VisitStatsResponse": VisitStatsResponse,
    "JournalPageResponse": JournalPageResponse,
    "SecurityCountsResponse": SecurityCountsResponse,
    "DailyVisitsResponse": DailyVisitsResponse,
    "RegisterResponse": RegisterResponse,
    "TokenPairResponse": TokenPairResponse,
    "RefreshResponse": RefreshResponse,
    "MessageResponse": MessageResponse,
    "ErrorResponse": ErrorResponse,
    # The bodies the auth routes read. Nine operations described none, so
    # a client generated from this document could reach every one of them
    # and fill in not one. The models are lenient by design and say so in
    # their own module: they hold the field names and the types, and the
    # sentences a route answers an absence with stay the route's.
    "CredentialsRequest": CredentialsRequest,
    "EmailRequest": EmailRequest,
    "VerifyEmailRequest": VerifyEmailRequest,
    "ResetPasswordRequest": ResetPasswordRequest,
    "ChangePasswordRequest": ChangePasswordRequest,
    "RefreshTokenRequest": RefreshTokenRequest,
    # Administration. The dashboard is written against these bodies, so
    # they were already a contract -- just an unwritten one.
    "CreateUserRequest": CreateUserRequest,
    "UpdateUserRolesRequest": UpdateUserRolesRequest,
    "CreateRoleRequest": CreateRoleRequest,
    "UpdateRolePermissionsRequest": UpdateRolePermissionsRequest,
    "UserResponseSchema": UserResponseSchema,
    "RoleResponseSchema": RoleResponseSchema,
}
"""Every schema the API speaks, taken from the models it validates with."""


ANONYMOUS_ROLE = "guest"
"""The role an unauthenticated caller acts under, per ``AuthenticationMiddleware``."""

_PATH_PARAMETER = re.compile(r"<(?:[^:<>]+:)?([^<>]+)>")
"""Flask's ``<name>`` and ``<converter:name>``, as OpenAPI's ``{name}``."""


def as_documented_path(rule: str) -> str:
    """
    A Flask rule written the way this document writes it.

    Args:
        rule: The rule as Flask holds it, e.g. ``/api/v1/links/<code>``.

    Returns:
        The same path in the document's spelling, ``/api/v1/links/{code}``.
    """
    return _PATH_PARAMETER.sub(r"{\1}", rule)


def _anonymous_may(app) -> "Any":
    """
    A question this document can ask about an anonymous caller.

    Asked of the running authorization service rather than read out of
    ``roles.yaml``: the file is the seed, the database is the answer, and
    a deployment that has edited ``guest`` has edited its own API. It is
    also the same call ``require_permission`` makes -- ``is_allowed(None,
    permission)`` -- so the document and the guard cannot disagree about
    what a visitor may do.

    Read through the application rather than imported, because this module
    describes the API and must not reach into infrastructure to do it;
    ``test_schemas_stay_above_infrastructure.py`` holds that, and caught
    the first version of this function reading the RBAC file directly.

    Args:
        app: The application whose container holds the service.

    Returns:
        A predicate taking a permission and answering whether an
        anonymous caller holds it. When there is no service to ask -- no
        container, or a database that cannot answer -- it answers False,
        which makes every guarded operation say a token is required: a
        stricter contract than the service enforces, never a looser one.
    """
    container = getattr(app, "container", None)
    service = None
    if container is not None:
        getter = getattr(container, "get_authorization_service", None)
        if getter is not None:
            try:
                service = getter()
            except Exception:  # pragma: no cover - a document is not worth a crash
                service = None

    # Remembered for the length of one document. The same permissions
    # repeat across operations -- `link:read_any` guards four of them --
    # and each ask is a role and permission lookup through the
    # authorization service, which for a database-backed one is a query.
    # The answer cannot change while a document is being assembled.
    answered: Dict[str, bool] = {}

    def may(permission: str) -> bool:
        if service is None:
            return False
        if permission not in answered:
            try:
                answered[permission] = bool(service.is_allowed(None, permission))
            except Exception:  # pragma: no cover - same reason
                answered[permission] = False
        return answered[permission]

    return may


AUTHENTICATION_OPERATIONS = "/api/v1/auth/"
"""Where a ``401`` is about the request rather than about a missing token.

Everywhere else a ``401`` means "no credentials, or credentials that do not
stand up", and the document has to say a token belongs there. Under this
prefix it means something else and a token would not help: sign-in answers
``401`` because the password is wrong, and refresh and sign-out read the
session cookie -- which is why ``AuthenticationMiddleware`` ignores a
failed ``Authorization`` header across this whole blueprint.

A prefix, not a list of the nine operations that are under it. The list
was the arrangement the middleware had first and was taken out of, and for
the fault that showed up there: a tenth route added to ``/auth`` is
handled by the rule and missed by the list, and the document would then
have declared ``[{}, {"bearerAuth": []}]`` -- "a token is optional here"
-- for a route that ignores tokens.

It is an exemption from the fallback below, and nothing else: an ``/auth``
operation that names a permission, or is marked ``requires_credentials``,
is decided before this is reached. ``change-password`` is the one that is,
and it lives here too.
"""


def security_for(permission: Optional[str], anonymous_may) -> list:
    """
    What an operation should declare about credentials.

    Three answers, and the middle one is the whole reason this is computed
    rather than typed:

    * **No decorator** -- nothing to declare. ``[]`` says so explicitly,
      which is not the same as saying nothing at all.
    * **Guarded by a permission the ``guest`` role holds** -- an anonymous
      caller may use it *and* a token is honoured. OpenAPI spells that
      ``[{}, {"bearerAuth": []}]``: the empty object is "no credentials",
      and a client generator reads it as optional.
    * **Guarded by a permission ``guest`` lacks** -- a token is required.

    Measured before this existed: of 39 operations, **two** declared
    ``security`` and 34 of the rest listed ``401``/``403`` among their own
    responses -- a document telling a reader that a call needs no
    credentials and answers 401. Swagger UI sends no token for such an
    operation, and a generated client has no place to put one.

    Args:
        permission: What ``require_permission`` put on the view, if any.
        anonymous_may: Predicate answering whether an anonymous caller
            holds a permission.

    Returns:
        The value for the operation's ``security`` key.
    """
    if permission is None:
        return []
    if anonymous_may(permission):
        return [{}, {"bearerAuth": []}]
    return [{"bearerAuth": []}]


def _add_security(paths: Dict[str, Any], app) -> Dict[str, Any]:
    """
    Say which operations need a token, reading the routes themselves.

    The truth lives on the view functions: ``require_permission`` leaves
    the permission it enforces on the wrapper, and this walks the route
    table to find it. Nothing here is a list to maintain -- an operation
    that gains or loses a guard changes what the document says about it on
    the next start-up.

    An operation the route table does not cover is left exactly as the
    hand-written table has it, which is how the two ``auth`` operations
    that already declare ``bearerAuth`` keep theirs.

    Args:
        paths: The path table, after the cross-cutting responses.
        app: The application whose routes describe the API.

    Returns:
        A copy carrying ``security`` on every operation the routes reach.
    """
    anonymous_may = _anonymous_may(app)

    described = {path: dict(operations) for path, operations in paths.items()}
    for rule in app.url_map.iter_rules():
        documented = as_documented_path(str(rule))
        operations = described.get(documented)
        if not operations:
            continue

        view = app.view_functions.get(rule.endpoint)
        permission = getattr(view, "required_permission", None)
        needs_a_caller = getattr(view, "requires_credentials", False)

        for method in (rule.methods or set()):
            verb = method.lower()
            if verb not in OPERATION_VERBS or verb not in operations:
                continue
            operation = operations[verb]
            if "security" in operation:
                # Written by hand in the path table, which is the answer:
                # nothing here overrules it.
                continue
            operation = dict(operation)

            if permission is not None:
                declared = security_for(permission, anonymous_may)
            elif needs_a_caller:
                # No decorator names a permission, and the route still
                # cannot be used by anybody anonymous -- the journals pick
                # theirs from the journal asked for, and changing your own
                # password is authorised by being signed in.
                declared = [{"bearerAuth": []}]
            elif documented.startswith(AUTHENTICATION_OPERATIONS):
                declared = []
            elif "401" in operation.get("responses", {}) or "403" in operation.get(
                "responses", {}
            ):
                # It answers a refusal that a credential can change, and
                # nothing here says a credential is required -- deleting a
                # guest link takes its deletion token, an owner's link
                # takes a session. Optional is the truthful answer, and it
                # is what puts the token box in front of the reader.
                declared = [{}, {"bearerAuth": []}]
            else:
                declared = []

            operation["security"] = declared
            operations[verb] = operation

    return described


def documented_paths() -> Dict[str, Any]:
    """
    The hand-written path table, for a reader that needs one field of it.

    ``build_openapi`` assembles the whole document -- component schemas
    from every request and response model, the cross-cutting responses,
    the security each operation declares -- and that costs about 4 ms, of
    which the schemas are most. A caller that wants only what each
    operation accepts in the query string pays all of it and throws the
    rest away, once per process at start-up and once per worker.

    The parameters are the same either way: the two passes that finish the
    document touch ``responses`` and ``security`` and nothing else, so
    what this returns is what the published document publishes. Measured
    across all 23 operations that declare a query parameter -- identical.

    Returns:
        The path table itself. Callers must not edit it: it is module
        state, and the document is built from it on every request.
    """
    return PATHS


def _ref(name: str) -> Dict[str, Any]:
    """Reference a component schema by name."""
    return {"$ref": f"#/components/schemas/{name}"}


def _json(name: str) -> Dict[str, Any]:
    """A JSON body of one schema."""
    return {"content": {"application/json": {"schema": _ref(name)}}}


def _html() -> Dict[str, Any]:
    """A body that is a page rather than an envelope."""
    return {"content": {"text/html": {"schema": {"type": "string"}}}}


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

UNDECLARED_INPUT_REFUSAL = (
    "a body field or a query parameter this operation does not declare"
)
"""The other answer every API operation can give, and none declared.

This service refuses what it does not understand rather than ignoring it:
a request body carrying an undeclared field is refused by
``StrictRequest``, and a query parameter no operation declares is refused
by ``middleware/query_strictness.py``, which reads *this* document to
decide. Both answer ``400 VALIDATION_ERROR`` with the name of what was
wrong.

Folded in here for the reason the two above are: OpenAPI 3.x cannot state
a response once for a document, and typing it into thirty-nine operations
is how a document falls behind. Measured before this line existed: the
contract run generated a request with one unknown parameter and got
``400`` from operations whose documented answers were ``200, 401, 403,
429`` -- the service refusing correctly and the document not saying so.
"""

def _throttle_headers() -> Dict[str, Any]:
    """
    Build the headers a refusal from the throttle carries.

    Built per call, not shared. One dict handed to every operation is one
    dict: editing the wording in a single operation would edit it
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

    Args:
        existing: The response object already declared, if any.
        reason: The reason to fold into its description.

    Returns:
        The response object to declare.
    """
    sentence = reason[0].upper() + reason[1:]

    if existing is None:
        return _error(sentence)

    described = existing.get("description")
    if not described:
        return {**existing, "description": sentence}

    # For a description that already says it. The table is written by hand,
    # so a reason can arrive already spelled out there -- and appending it
    # again reads as a stutter rather than as a bug. Not about rebuilding:
    # the merge writes a new table and never into ``PATHS``, so every
    # rebuild starts from the same untouched entry.
    if reason in described:
        return dict(existing)

    return {**existing, "description": f"{described}; or {reason}"}


def _add_cross_cutting_responses(paths: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fold in the answers every operation can give and few of them declared.

    Two layers sit in front of the whole application and were barely
    mentioned here: the throttle can answer 429 to any request, and only
    some operations say so; the CSRF layer answers 403 to any
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

            if "requestBody" in value:
                # Flask answers 415 when a body is expected and the
                # request does not carry `Content-Type: application/json`
                # -- including when it carries no body at all. Measured by
                # the contract run: `POST /api/v1/auth/verify` with no
                # body answered 415 against a document declaring 200, 400,
                # 403 and 429.
                responses["415"] = _merge_response(
                    responses.get("415"),
                    "a body that is not declared as JSON",
                )

            if path.startswith("/api/v1"):
                # Under `/api/v1` only, which is where both rules apply:
                # a page reads what it knows of the query string and
                # ignores the rest, deliberately.
                responses["400"] = _merge_response(
                    responses.get("400"), UNDECLARED_INPUT_REFUSAL
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
    "description": (
        "The short code, 6-10 of A-Z a-z 0-9 _ -. A few names the service "
        "answers to itself -- health, static, dashboard and the like -- "
        "cannot be claimed."
    ),
    "schema": {"type": "string"},
}

USER_PARAMETER = {
    "name": "user_id",
    "in": "path",
    "required": True,
    "description": "Identifier of the account, as the account listing gives it.",
    "schema": {"type": "string"},
}

ROLE_PARAMETER = {
    "name": "role_name",
    "in": "path",
    "required": True,
    "description": "Name of the role, as the role listing gives it.",
    "schema": {"type": "string"},
}

_DEPENDENCY = {
    "type": "boolean",
    "description": "True when the dependency answered.",
}

_LOG_CHANNEL = {
    "type": "object",
    "properties": {
        # A string, not a boolean: it names the implementation doing the
        # work -- "structlog", "standard_audit", "not started".
        "active": {"type": "string"},
        "dropped_calls": {"type": "integer"},
        "failed_checks": {"type": "integer"},
        "lost_log_lines": {"type": "integer"},
        # The state the three counters cannot report. They count losses,
        # and a chain that reports itself unwell produces none of them
        # while nothing is being written through it -- nor does `active`
        # move where there is nowhere to move the work to.
        "last_check": {
            "type": "string",
            "enum": ["not run", "healthy", "unhealthy", "probe failed"],
            "description": (
                "What the last background round found the active "
                "implementation to be. `not run` where no round has "
                "reached a verdict yet, including a chain built without "
                "failover; `probe failed` where the probe itself threw, "
                "which answers nothing and is why no work is moved on "
                "one."
            ),
        },
    },
}

HEALTH_SCHEMA = {
    "type": "object",
    "properties": {
        "database": _DEPENDENCY,
        "database_schema": {
            "type": "boolean",
            "description": (
                "Whether the database reached holds this application's "
                "tables. Apart from `database` for the reason "
                "`cache_configured` is apart from `cache`: one boolean "
                "cannot say both \"it answered\" and \"it holds what we "
                "need\". A database the migration never reached answers "
                "every connectivity probe and answers 500 to every "
                "request; `database` true with this false is that state, "
                "and it is the one `/health` reports as `no_schema`."
            ),
        },
        "cache": _DEPENDENCY,
        "cache_configured": {
            "type": "boolean",
            "description": (
                "Whether a cache backend is configured at all. A cache "
                "nobody configured cannot be down, so it answers `cache` "
                "true; this tells that apart from a cache that is working."
            ),
        },
        "task_queue": _DEPENDENCY,
        "task_queue_configured": {
            "type": "boolean",
            "description": (
                "Whether there is a broker behind the queue at all. With "
                "`CELERY_ENABLED=false` the work is done during the "
                "request, so `task_queue` answers true; this tells that "
                "apart from workers that are answering. The sibling of "
                "`cache_configured`, and it was missing: a deployment "
                "with neither cache nor broker reported the two "
                "differently for one and the same state."
            ),
        },
        "rate_limiter": _DEPENDENCY,
        "components": {
            "type": "object",
            "description": (
                "What each dependency is doing, judged once by the "
                "snapshot rather than worked out again by every reader. "
                "The booleans above are what was measured; this is what "
                "they mean, in the same words `/health` publishes -- and "
                "it says two things they cannot: a database that answers "
                "and holds no schema, and a cache keeping entries in the "
                "process with no server behind it."
            ),
            "additionalProperties": {
                "type": "string",
                "enum": [
                    "ok", "unavailable", "timeout", "no_schema",
                    "in_process", "disabled", "inline",
                    "enforcing", "not_enforcing",
                ],
            },
        },
        "timed_out": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Dependencies that did not answer within the check's "
                "budget. Reported false above as well, and named here "
                "because \"did not answer in time\" says which one is "
                "hanging where \"answered no\" does not."
            ),
        },
        "logging": {
            "type": "object",
            "description": (
                "Present only where a failover logger is configured."
            ),
            "properties": {
                "worker": {
                    "type": "integer",
                    "description": (
                        "Process the counters were taken in. They live in "
                        "one worker's memory and a deployment runs "
                        "several, so they are that worker's, not the "
                        "service's."
                    ),
                },
                "logger": _LOG_CHANNEL,
                "audit": _LOG_CHANNEL,
                "journals_written": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["application", "error", "audit"],
                    },
                    "description": (
                        "Journals this worker opened when it started. "
                        "About the files, not the chains: one that broke "
                        "afterwards is still named here, and what the "
                        "chain writing it found last is that chain's "
                        "`last_check`. Empty where the deployment writes "
                        "no files at all, which `LOG_TO_FILE=false` "
                        "makes a configuration rather than a fault -- "
                        "and which an empty `journals_unavailable` "
                        "cannot be told apart from otherwise."
                    ),
                },
                "journals_unavailable": {
                    "type": "array",
                    "description": (
                        "Journals this worker could not open when it "
                        "started, so nothing is being written to them. "
                        "Empty on a healthy deployment. No counter above "
                        "reports it: a handler that was never built "
                        "drops nothing."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "journal": {
                                "type": "string",
                                "enum": ["application", "error", "audit"],
                                "description": (
                                    "Which journal, by the names the "
                                    "journal reader uses."
                                ),
                            },
                            "reason": {
                                "type": "string",
                                "description": (
                                    "What the operating system said, "
                                    "naming the path and the cause."
                                ),
                            },
                        },
                        "required": ["journal", "reason"],
                    },
                },
            },
        },
    },
    "required": [
        "database", "database_schema", "cache", "cache_configured",
        "task_queue_configured",
        "task_queue", "rate_limiter", "components", "timed_out",
    ],
}
"""
The health body, written out because the endpoint assembles it by hand.

Everything else in this document is a Pydantic model's own schema, which
is why it cannot drift from what the endpoint validates. This one can:
``AdminApiController.get_health`` builds a dict. A test holds the two
together instead.
"""

JOURNAL_SEARCH_PARAMETERS = [
    {
        "name": name,
        "in": "query",
        "required": False,
        "description": description,
        "schema": schema,
    }
    for name, description, schema in (
        (
            "event_type",
            "Match the event's own type exactly, as the audit journal "
            "writes it: LOGIN_FAILED, ROLES_CHANGED, URL_ACCESSED. "
            "LOGGING_CHAIN_PROBE is the one type a read without terms "
            "does not return: the logging chains write a probe record "
            "into the journal they are probing, and naming this type is "
            "how to see them.",
            {"type": "string", "maxLength": 64},
        ),
        (
            "account",
            "Match an account id against both names an event can carry it "
            "under -- user_id, whoever acted, and target_user_id, whoever "
            "was acted upon. One term rather than two, because searching "
            "one name shows half of what happened to an account without "
            "saying so.",
            {"type": "string", "maxLength": 64},
        ),
        (
            "remote_addr",
            "Match the address a request came from, exactly: a substring "
            "of an address is a different address.",
            {"type": "string", "maxLength": 64},
        ),
        (
            "short_code",
            "Match the link an event was about, exactly.",
            {"type": "string", "maxLength": 64},
        ),
        (
            "since",
            "Earliest stamp to include. A whole ISO 8601 stamp in UTC or "
            "any prefix of one: 2026-08-18 is that whole day, "
            "2026-08-18T14 that hour. Both ends are inclusive.",
            {"type": "string", "example": "2026-08-18"},
        ),
        (
            "until",
            "Latest stamp to include, in the same shape as since.",
            {"type": "string", "example": "2026-08-18T14"},
        ),
    )
]
"""The six terms a journal read may be narrowed by.

Built from a list because the six differ only in name and wording, and six
near-identical dictionaries invite the copy that leaves one field's
description on another's parameter.

A search costs more than a tail -- measured, 117 to 136 ms against 2 ms,
since it scans up to fifty thousand lines rather than stopping at the page
-- so it is a thing a caller asks for rather than the default.
"""


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
                        "an account. This header is the only place it is "
                        "read from: a query parameter is not accepted, and "
                        "sending it that way answers 401 exactly as a "
                        "forged token does. Deliberate -- a token in a "
                        "query string reaches browser history, the "
                        "`Referer` of the next request, and every proxy "
                        "log on the way."
                    ),
                    "schema": {"type": "string"},
                },
            ],
            "responses": {
                "200": {"description": "Deleted", **_json("MessageResponse")},
                # One code for three situations -- no token, a forged
                # one, and a good one sent somewhere this route does not
                # read. Telling them apart would tell an unauthenticated
                # caller which of their guesses was closer.
                "401": _error(
                    "Neither an account nor a valid token in "
                    "X-Deletion-Token"
                ),
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
    "/api/v1/links/{short_code}/qr": {
        "get": {
            "summary": "Draw the short link as a QR code",
            "description": (
                "The image encodes the **short** address, never the "
                "destination: a square carrying the destination would "
                "scan correctly and bypass the counters, the expiry and "
                "the deletion the link exists to provide.\n\n"
                "Withholds nothing, because there is nothing to withhold "
                "-- the caller had to know the code to ask. The code is "
                "still resolved first, so an address that leads nowhere "
                "is a 404 rather than a square that leads to one.\n\n"
                "SVG, with both a `viewBox` and a default `width`, so it "
                "scales in a page and still has a size on its own."
            ),
            "tags": ["links"],
            "parameters": [CODE_PARAMETER],
            "responses": {
                "200": {
                    "description": "The code, as an SVG document",
                    "content": {
                        "image/svg+xml": {
                            "schema": {"type": "string", "format": "binary"}
                        }
                    },
                },
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
            "parameters": [
                {
                    "name": "limit",
                    "in": "query",
                    "required": False,
                    "description": (
                        "How many links to return. Brought inside the "
                        "bounds rather than refused, the way the account "
                        "listing does it and the journals do not."
                    ),
                    "schema": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_PAGE_SIZE,
                        "default": 50,
                    },
                },
                {
                    "name": "offset",
                    "in": "query",
                    "required": False,
                    "description": (
                        "How many to skip. Below zero is read as zero."
                    ),
                    "schema": {"type": "integer", "minimum": 0, "default": 0},
                },
            ],
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
    "/api/v1/stats/visits": {
        "get": {
            "summary": "Recorded visits over a span",
            "description": (
                "When links were opened, not only how often. The "
                "service-wide answer needs stats:view_basic, which the "
                "seeded guest role carries. `scope=mine` narrows it to "
                "the caller's own links and needs link:view_own and a "
                "session. The top-links table needs "
                "stats:view_full on top and comes back empty without it -- "
                "a short code is somebody's link, which is a different "
                "disclosure than a count. Robots are counted and reported "
                "separately rather than dropped, so this total and "
                "`urls.clicks` agree."
            ),
            "tags": ["stats"],
            "parameters": [
                {
                    "name": "period", "in": "query", "required": False,
                    "schema": {"type": "string",
                               "enum": ["24h", "7d", "30d", "90d"],
                               "default": "7d"},
                    "description": "Span, and with it how finely it is cut.",
                },
                {
                    "name": "scope", "in": "query", "required": False,
                    "schema": {"type": "string",
                               "enum": ["service", "mine"],
                               "default": "service"},
                },
                {
                    "name": "code", "in": "query", "required": False,
                    "schema": {"type": "string"},
                    "description": (
                        "Restrict to one link, by its short code. Checked "
                        "against that link's owner rather than against the "
                        "statistics permissions: the link's owner, an "
                        "administrator and a holder of stats:view_any may "
                        "ask, and nobody else. A code no link carries is "
                        "404."
                    ),
                },
            ],
            "responses": {
                "200": {"description": "The span",
                        **_json("VisitStatsResponse")},
                "400": _error("Unknown period, or a malformed code"),
                "401": _error("scope=mine without a session"),
                "403": _error("Not entitled to the statistics"),
                # Named here as well as in the parameter's own description,
                # which said "A code no link carries is 404" while the list
                # of answers did not include it. Found by the contract run:
                # `?code=<a code nothing carries>` answered 404
                # LINK_NOT_FOUND against a document declaring 200, 400,
                # 401, 403 and 429.
                "404": _error("No link carries that code"),
            },
        }
    },
    "/api/v1/stats/visits/daily": {
        "get": {
            "summary": "Visits per day, past the retention window",
            "description": (
                "Reads the rolled-up days and the raw visits together, so "
                "the answer reaches further back than the raw rows do. "
                "Days with no visits are present with a zero, so a chart "
                "draws a gap rather than joining two distant points. "
                "Scoped like /stats/visits: stats:view_basic for the "
                "service-wide answer, link:view_own for `scope=mine`."
            ),
            "tags": ["stats"],
            "parameters": [
                {
                    "name": "days", "in": "query", "required": False,
                    "schema": {"type": "integer", "minimum": 1,
                               "maximum": 730, "default": 90},
                },
                {
                    "name": "scope", "in": "query", "required": False,
                    "schema": {"type": "string",
                               "enum": ["service", "mine"],
                               "default": "service"},
                },
                {
                    "name": "code", "in": "query", "required": False,
                    "schema": {"type": "string"},
                    "description": (
                        "Restrict to one link, by its short code. Gated as "
                        "on /stats/visits: by that link's owner, not by the "
                        "statistics permissions."
                    ),
                },
            ],
            "responses": {
                "200": {"description": "One entry per day",
                        **_json("DailyVisitsResponse")},
                "400": _error("days out of range, or a malformed code"),
                "401": _error("scope=mine without a session"),
                "403": _error("Not entitled to the statistics"),
                # As on the span above, and found the same way.
                "404": _error("No link carries that code"),
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
                "The password must be at least 8 characters and at most "
                "64, must not be made of whitespace alone, and must not be "
                "one attackers already have. A password in a script that "
                "needs more than one byte per character reaches the "
                "ceiling sooner. No composition rules. "
                "Answers 202 whether or not the address was already "
                "registered, and returns no account details either way -- "
                "telling the two apart would say who is registered. The "
                "address is mailed in both cases: a confirmation link if it "
                "was free, a notice that an account exists if it was not."
            ),
            "tags": ["auth"],
            "requestBody": {"required": True, **_json("CredentialsRequest")},
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
            "requestBody": {"required": True, **_json("CredentialsRequest")},
            "responses": {
                "200": {"description": "Tokens", **_json("TokenPairResponse")},
                "400": _error("Malformed body or malformed email"),
                "401": _error(
                    "Refused. Wrong credentials, an inactive account and an "
                    "address nobody has confirmed are one answer -- "
                    "INVALID_CREDENTIALS, with the same sentence -- so that "
                    "the reply cannot be used to tell whether a password "
                    "landed. The journal keeps the three apart"
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
        },
        "post": {
            "summary": "Confirm an email address",
            "description": (
                "What the confirmation page sends, and the same act as "
                "the GET above. The token is read from the query string "
                "first and from the JSON body only when the query "
                "carries none, so a page that posts `{\"token\": ...}` "
                "and a link mailed before that page existed both work. "
                "Answers alike for every way a token can fail, for the "
                "reason given on the GET."
            ),
            "tags": ["auth"],
            "parameters": [
                {
                    "name": "token",
                    "in": "query",
                    "required": False,
                    "schema": {"type": "string"},
                    "description": (
                        "The token, when it is not in the body."
                    ),
                }
            ],
            # Not required, alone among the bodies that carry a token:
            # the query parameter above is the other way in, and a
            # request that uses it sends no body at all.
            "requestBody": {"required": False, **_json("VerifyEmailRequest")},
            "responses": {
                "200": {
                    "description": "The address is confirmed",
                    **_json("MessageResponse"),
                },
                "400": _error("The link is not usable"),
            },
        },
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
            "requestBody": {"required": True, **_json("EmailRequest")},
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
    "/api/v1/auth/forgot-password": {
        "post": {
            "summary": "Ask for a password reset link",
            "description": (
                "Answers 202 whether the address is registered, "
                "unconfirmed, deactivated or unknown, with one sentence "
                "that fits all four. A link is mailed only to an address "
                "that has a live, confirmed account behind it; an "
                "unconfirmed one is not a mailbox this service has any "
                "evidence about."
            ),
            "tags": ["auth"],
            "requestBody": {"required": True, **_json("EmailRequest")},
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
    "/api/v1/auth/reset-password": {
        "post": {
            "summary": "Set a new password from a mailed token",
            "description": (
                "Takes token and new_password. Answers the same whether "
                "the token is unknown, already spent, expired, or names "
                "an account that is gone -- telling them apart would say "
                "who is registered. Nobody is signed in by it: the new "
                "password is used on the sign-in page. Every session the "
                "account held is revoked."
            ),
            "tags": ["auth"],
            "requestBody": {"required": True, **_json("ResetPasswordRequest")},
            "responses": {
                "200": {"description": "Changed", **_json("MessageResponse")},
                "400": _error(
                    "The token cannot be spent, or the password policy "
                    "refuses the new password"
                ),
                "429": _error("Too many attempts from this address"),
            },
        }
    },
    "/api/v1/auth/change-password": {
        "post": {
            "summary": "Change the signed-in account's own password",
            "description": (
                "Takes current_password and new_password. The account is "
                "the one the request is authenticated as and is never read "
                "from the body. Every session the account had is revoked, "
                "the caller's included, and the new pair in the answer is "
                "opened after that -- so the client that made the change "
                "stays signed in and no other device does."
            ),
            "tags": ["auth"],
            "requestBody": {"required": True, **_json("ChangePasswordRequest")},
            "responses": {
                "200": {
                    "description": "Changed; a new pair for this client",
                    **_json("RefreshResponse"),
                },
                "400": _error(
                    "The current password is wrong, the new one repeats it, "
                    "or the password policy refuses it"
                ),
                "401": _error("Nobody is authenticated"),
                "429": _error("Too many attempts from this address"),
            },
        }
    },
    "/api/v1/auth/refresh": {
        "post": {
            "summary": "Rotate the refresh token",
            "tags": ["auth"],
            # A browser sends none: its token is in the HttpOnly cookie,
            # which is where this route looks first.
            "requestBody": {"required": False, **_json("RefreshTokenRequest")},
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
            # Optional for the same reason as /refresh, and this route
            # also ends a session named by the access token alone.
            "requestBody": {"required": False, **_json("RefreshTokenRequest")},
            "responses": {
                "200": {"description": "Ended", **_json("MessageResponse")}
            },
        }
    },
    # --- Administration ----------------------------------------------
    #
    # Left out of this document until now, on the grounds that it is not
    # part of the public API. It is not public, and that is a matter of
    # who may call it rather than of whether it is written down: every
    # operation below is behind a permission an ordinary account does not
    # hold, and saying so here is what tells a reader which permission
    # that is. Undocumented, the operator's own surface was the one part
    # of the service with no contract -- while the dashboard that drives
    # it was written against these exact bodies.
    #
    # Each operation names its permission, because that is the thing a
    # reader cannot recover from the shapes.
    "/api/v1/admin/users": {
        "get": {
            "summary": "List accounts",
            "description": (
                "Needs admin:view_users. Paginated through limit and "
                "offset; the default page is a hundred, and there is no "
                "total -- ask for one more than you mean to show to learn "
                "whether another page exists. Accounts come back in "
                "address order, so a window means the same thing from one "
                "request to the next."
            ),
            "tags": ["admin"],
            "parameters": [
                {
                    "name": "limit",
                    "in": "query",
                    "required": False,
                    "description": (
                        "How many accounts to return. Brought inside the "
                        "bounds rather than refused, unlike the journal "
                        "endpoints: a window is a convenience here, not a "
                        "claim about how much there is."
                    ),
                    "schema": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_PAGE_SIZE,
                        "default": 100,
                    },
                },
                {
                    "name": "offset",
                    "in": "query",
                    "required": False,
                    "description": (
                        "How many to skip. Below zero is read as zero."
                    ),
                    "schema": {"type": "integer", "minimum": 0, "default": 0},
                },
            ],
            "responses": {
                "200": {
                    "description": "The page of accounts",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "array",
                                "items": _ref("UserResponseSchema"),
                            }
                        }
                    },
                },
                "401": _error("Nobody is authenticated"),
                "403": _error("The caller does not hold admin:view_users"),
            },
        },
        "post": {
            "summary": "Create an account",
            "description": (
                "Needs admin:manage_users. The account is created "
                "confirmed -- an operator making an account for somebody "
                "is the confirmation. Omitting roles gives the default one."
            ),
            "tags": ["admin"],
            "requestBody": {"required": True, **_json("CreateUserRequest")},
            "responses": {
                "201": {"description": "Created", **_json("UserResponseSchema")},
                "400": _error(
                    "Malformed body, or a role no account may wear -- "
                    "guest, which is the role an unauthenticated request "
                    "acts under"
                ),
                "401": _error("Nobody is authenticated"),
                "403": _error("The caller does not hold admin:manage_users"),
                "404": _error("No role carries one of those names"),
                "409": _error("That address is already registered"),
                "415": _error("A body that is not declared application/json"),
            },
        },
    },
    "/api/v1/admin/users/{user_id}": {
        "get": {
            "summary": "Read one account",
            "description": "Needs admin:view_users.",
            "tags": ["admin"],
            "parameters": [USER_PARAMETER],
            "responses": {
                "200": {"description": "The account", **_json("UserResponseSchema")},
                "401": _error("Nobody is authenticated"),
                "403": _error("The caller does not hold admin:view_users"),
                "404": _error("No account carries that id"),
            },
        },
        "delete": {
            "summary": "Delete an account",
            "description": (
                "Needs admin:manage_users. Refused when it would leave the "
                "service with no administrator; the links the account made "
                "outlive it."
            ),
            "tags": ["admin"],
            "parameters": [USER_PARAMETER],
            "responses": {
                "200": {"description": "Deleted", **_json("MessageResponse")},
                "401": _error("Nobody is authenticated"),
                "403": _error(
                    "The caller does not hold admin:manage_users, or this "
                    "would leave the system without an administrator"
                ),
                "404": _error("No account carries that id"),
            },
        },
    },
    "/api/v1/admin/users/{user_id}/roles": {
        "put": {
            "summary": "Replace an account's roles",
            "description": (
                "Needs admin:manage_users. A replacement, not an addition: "
                "what is not in the list is taken away. Refused when it "
                "would remove the last administrator's admin role."
            ),
            "tags": ["admin"],
            "parameters": [USER_PARAMETER],
            "requestBody": {"required": True, **_json("UpdateUserRolesRequest")},
            "responses": {
                "200": {"description": "The account", **_json("UserResponseSchema")},
                "400": _error(
                    "Malformed body, or a role no account may wear -- "
                    "guest, which is the role an unauthenticated request "
                    "acts under"
                ),
                "401": _error("Nobody is authenticated"),
                "403": _error(
                    "The caller does not hold admin:manage_users, or this "
                    "would leave the system without an administrator"
                ),
                "404": _error(
                    "No account carries that id, or no role carries one of "
                    "those names"
                ),
                "415": _error("A body that is not declared application/json"),
            },
        }
    },
    "/api/v1/admin/users/{user_id}/verify-email": {
        "post": {
            "summary": "Confirm an address without a mailed link",
            "description": (
                "Needs admin:manage_users. Marks the address as confirmed "
                "on the operator's word, for the cases the mailed link "
                "cannot cover -- the message never arrived, the address is "
                "a list nobody reads, the deployment sends no mail. Any "
                "outstanding confirmation tokens are spent along with it, "
                "so a link still sitting in a mailbox stops working. "
                "Idempotent: an already confirmed account answers 200."
            ),
            "tags": ["admin"],
            "parameters": [USER_PARAMETER],
            "responses": {
                "200": {"description": "The account", **_json("UserResponseSchema")},
                "401": _error("Nobody is authenticated"),
                "403": _error("The caller does not hold admin:manage_users"),
                "404": _error("No account carries that id"),
            },
        }
    },
    "/api/v1/admin/users/{user_id}/resend-verification": {
        "post": {
            "summary": "Send the confirmation message again",
            "description": (
                "Needs admin:manage_users. Runs the same use case as the "
                "public endpoint, addressed by account id rather than by "
                "email, and answers with the address it went to. Issuing a "
                "new token retires the ones outstanding."
            ),
            "tags": ["admin"],
            "parameters": [USER_PARAMETER],
            "responses": {
                "202": {"description": "Accepted", **_json("MessageResponse")},
                "401": _error("Nobody is authenticated"),
                "403": _error("The caller does not hold admin:manage_users"),
                "404": _error("No account carries that id"),
            },
        }
    },
    "/api/v1/admin/users/{user_id}/deactivate": {
        "post": {
            "summary": "Suspend an account",
            "description": (
                "Needs admin:manage_users. The account stops being able to "
                "sign in; its links go on resolving. Refused when it would "
                "leave the service with no administrator."
            ),
            "tags": ["admin"],
            "parameters": [USER_PARAMETER],
            "responses": {
                "200": {"description": "The account", **_json("UserResponseSchema")},
                "401": _error("Nobody is authenticated"),
                "403": _error(
                    "The caller does not hold admin:manage_users, or this "
                    "would leave the system without an administrator"
                ),
                "404": _error("No account carries that id"),
            },
        }
    },
    "/api/v1/admin/users/{user_id}/activate": {
        "post": {
            "summary": "Restore a suspended account",
            "description": "Needs admin:manage_users.",
            "tags": ["admin"],
            "parameters": [USER_PARAMETER],
            "responses": {
                "200": {"description": "The account", **_json("UserResponseSchema")},
                "401": _error("Nobody is authenticated"),
                "403": _error("The caller does not hold admin:manage_users"),
                "404": _error("No account carries that id"),
            },
        }
    },
    "/api/v1/admin/users/{user_id}/stats": {
        "get": {
            "summary": "One account's traffic",
            "description": (
                "Needs admin:view_users. The same figures /api/v1/stats/mine "
                "gives an account about itself."
            ),
            "tags": ["admin"],
            "parameters": [USER_PARAMETER],
            "responses": {
                "200": {
                    "description": "The account's totals and recent links",
                    **_json("MyStatsResponse"),
                },
                "401": _error("Nobody is authenticated"),
                "403": _error("The caller does not hold admin:view_users"),
                "404": _error("No account carries that id"),
            },
        }
    },
    "/api/v1/admin/roles": {
        "get": {
            "summary": "List roles",
            "description": "Needs admin:view_roles.",
            "tags": ["admin"],
            "responses": {
                "200": {
                    "description": "Every role, with its permissions",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "array",
                                "items": _ref("RoleResponseSchema"),
                            }
                        }
                    },
                },
                "401": _error("Nobody is authenticated"),
                "403": _error("The caller does not hold admin:view_roles"),
            },
        },
        "post": {
            "summary": "Create a role",
            "description": (
                "Needs admin:manage_roles. Permissions are named from the "
                "fixed set the service defines; a name outside it is a 400."
            ),
            "tags": ["admin"],
            "requestBody": {"required": True, **_json("CreateRoleRequest")},
            "responses": {
                "201": {"description": "Created", **_json("RoleResponseSchema")},
                "400": _error("Malformed body, or a permission that does not exist"),
                "401": _error("Nobody is authenticated"),
                "403": _error("The caller does not hold admin:manage_roles"),
                "409": _error("A role of that name already exists"),
                "415": _error("A body that is not declared application/json"),
            },
        },
    },
    "/api/v1/admin/roles/{role_name}": {
        "get": {
            "summary": "Read one role",
            "description": "Needs admin:view_roles.",
            "tags": ["admin"],
            "parameters": [ROLE_PARAMETER],
            "responses": {
                "200": {"description": "The role", **_json("RoleResponseSchema")},
                "401": _error("Nobody is authenticated"),
                "403": _error("The caller does not hold admin:view_roles"),
                "404": _error("No role carries that name"),
            },
        },
        "delete": {
            "summary": "Delete a role",
            "description": (
                "Needs admin:manage_roles. System roles -- guest, user, "
                "analyst, admin -- are protected and cannot be deleted. "
                "Accounts holding the role lose it."
            ),
            "tags": ["admin"],
            "parameters": [ROLE_PARAMETER],
            "responses": {
                "200": {"description": "Deleted", **_json("MessageResponse")},
                "400": _error("The role is a system role"),
                "401": _error("Nobody is authenticated"),
                "403": _error(
                    "The caller does not hold admin:manage_roles, or the "
                    "change would leave the system without an administrator"
                ),
                "404": _error("No role carries that name"),
            },
        },
    },
    "/api/v1/admin/roles/{role_name}/permissions": {
        "put": {
            "summary": "Replace a role's permissions",
            "description": (
                "Needs admin:manage_roles. A replacement, not an addition. "
                "System roles are protected and answer 400."
            ),
            "tags": ["admin"],
            "parameters": [ROLE_PARAMETER],
            "requestBody": {
                "required": True,
                **_json("UpdateRolePermissionsRequest"),
            },
            "responses": {
                "200": {"description": "The role", **_json("RoleResponseSchema")},
                "400": _error(
                    "Malformed body, a permission that does not exist, or a "
                    "system role"
                ),
                "401": _error("Nobody is authenticated"),
                "403": _error(
                    "The caller does not hold admin:manage_roles, or the "
                    "change would leave the system without an administrator"
                ),
                "404": _error("No role carries that name"),
                "415": _error("A body that is not declared application/json"),
            },
        }
    },
    "/api/v1/admin/health": {
        "get": {
            "summary": "Infrastructure health",
            "description": (
                "Needs admin:view_system_health. Each dependency reports "
                "reachable or not; the logging block appears only where a "
                "failover logger is configured, and its counters are the "
                "only runtime word on whether the audit trail is still "
                "being written."
            ),
            "tags": ["admin"],
            "responses": {
                # Assembled by the endpoint rather than serialised from a
                # model, so it is written out here. The rest of this
                # document points at the Pydantic models the endpoints
                # validate against; this one has none to point at.
                "200": {
                    "description": "What each dependency answered",
                    "content": {
                        "application/json": {"schema": HEALTH_SCHEMA}
                    },
                },
                "401": _error("Nobody is authenticated"),
                "403": _error("The caller does not hold admin:view_system_health"),
            },
        }
    },
    "/api/v1/journals/counters": {
        "get": {
            "summary": "Count the security events of a span",
            "description": (
                "How many sign-ins, refusals, account and role changes "
                "and journal reads fell inside a span, in total and split "
                "into intervals for a chart. Read under audit:view -- the "
                "permission that opens the audit journal -- because these "
                "figures are that journal counted, and a count is not a "
                "weaker version of a record but the same information "
                "aggregated. admin:all does not carry it. Redirects are "
                "not here: they are counted in link_visits and served by "
                "the visit endpoints."
            ),
            "tags": ["journals"],
            "parameters": [
                {
                    "name": "period",
                    "in": "query",
                    "required": False,
                    "description": (
                        "Which span, from a fixed set. Free-form spans "
                        "are not offered: a caller naming its own span "
                        "and bucket count can ask for a million buckets. "
                        "The same four the visit charts use, and cut "
                        "from the same table, so two answers about "
                        "one service cover the same days."
                    ),
                    "schema": {
                        "type": "string",
                        "enum": ["24h", "7d", "30d", "90d"],
                        "default": "7d",
                    },
                },
            ],
            "responses": {
                "200": {
                    "description": "The counts and the series behind them",
                    **_json("SecurityCountsResponse"),
                },
                "400": _error("period is not one of the four on offer"),
                "401": _error("Nobody is authenticated"),
                "403": _error("The caller does not hold audit:view"),
            },
        }
    },
    "/api/v1/journals/{journal}": {
        "get": {
            "summary": "Read the end of a journal",
            "description": (
                "The last lines of application, error or audit, oldest "
                "first. The audit journal needs audit:view and the other "
                "two need logs:view -- which permission applies is decided "
                "by the journal asked for, so this operation answers 403 "
                "to a caller entitled to one of them and not the other. "
                "admin:all does not carry audit:view. A name that is not "
                "one of the three is 404, and no path can be spelled: the "
                "three names are the whole of what exists."
            ),
            "tags": ["journals"],
            "parameters": [
                {
                    "name": "journal",
                    "in": "path",
                    "required": True,
                    "description": "Which journal to read.",
                    "schema": {
                        "type": "string",
                        "enum": ["application", "error", "audit"],
                    },
                },
                {
                    "name": "limit",
                    "in": "query",
                    "required": False,
                    "description": (
                        "Most lines to return. Refused above the ceiling "
                        "rather than trimmed to it, so a caller is never "
                        "told the journal is shorter than it is."
                    ),
                    "schema": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": HARD_LIMIT,
                        "default": DEFAULT_LINES,
                    },
                },
                {
                    "name": "archives",
                    "in": "query",
                    "required": False,
                    "description": (
                        "Continue into the rotated files once the live "
                        "journal is exhausted. Costs whole files: a gzip "
                        "archive cannot be read from its end."
                    ),
                    "schema": {"type": "boolean", "default": False},
                },
                {
                    "name": "follow",
                    "in": "query",
                    "required": False,
                    "description": (
                        "Say that this read continues one already made -- "
                        "a viewer refreshing the tail it is displaying. "
                        "Changes nothing about the answer; it keeps the "
                        "poll out of the audit journal, which would "
                        "otherwise gain twelve lines a minute per reader."
                    ),
                    "schema": {"type": "boolean", "default": False},
                },
                *JOURNAL_SEARCH_PARAMETERS,
            ],
            "responses": {
                "200": {
                    "description": "The end of the journal",
                    **_json("JournalPageResponse"),
                },
                "400": _error(
                    f"limit outside 1..{HARD_LIMIT}, a search term longer "
                    "than 64 characters, or a time bound that is not an "
                    "ISO 8601 stamp in UTC or a prefix of one"
                ),
                "401": _error("Nobody is authenticated"),
                "403": _error(
                    "The caller does not hold the permission this journal "
                    "is read under"
                ),
                "404": _error("No journal is called that"),
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
                # A page, not an envelope. This route is followed by a
                # browser -- it is the whole product -- so a code nobody
                # carries is answered with the service's own 404 page, and
                # the two refusals below are the only ones in this document
                # that are not JSON. Declared as what they are: the
                # contract run read `text/html; charset=utf-8` against a
                # document promising `application/json`.
                "404": {
                    "description": "No link carries that code",
                    **_html(),
                },
                "410": {"description": "The link has expired", **_html()},
            },
        }
    },
}
"""What the routing table and the decorators know, written out once."""


@lru_cache(maxsize=1)
def _component_schemas() -> Dict[str, Any]:
    """
    Every schema the document publishes, built once per process.

    Derived from ``MODELS``, which is module state and does not change
    while the process runs, and it is the expensive half of assembling the
    document: measured, 3.57 ms of the 3.83 ms a build costs, paid again on
    every request to ``/api/openapi.json`` and ``/api/docs``.

    Cached, which means the mapping is shared between requests -- so
    nothing may edit it in place. Both callers hand the document straight
    to ``jsonify`` or to a template, and the two passes that finish it
    write under ``paths``; a future one that rewrites a component schema
    has to copy first.

    Returns:
        ``{name: schema}`` for every request and response model.
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
    return schemas


def build_openapi(
    base_url: str, version: str = "1.0.0", app=None
) -> Dict[str, Any]:
    """
    Assemble the OpenAPI document.

    Args:
        base_url: Public base URL of this deployment.
        version: Version to report for the API.
        app: The application whose routes say which operations need a
            token. Defaults to the one in the current application context,
            which is where both callers stand; passed explicitly by tests
            that build a document outside one. Without either, the
            operations carry only what the table below declares -- and
            what the service actually serves is always built with an
            application, because a document is only ever asked for through
            a request.

    Returns:
        The document, ready to be serialized as JSON.
    """
    if app is None:
        # `current_app` is a proxy and raises outside a context rather than
        # answering None, so the absence is asked about rather than caught
        # after the fact.
        from flask import current_app, has_app_context

        # The proxy itself, not the object behind it: everything below asks
        # it for `url_map`, `view_functions` and `container`, which it
        # forwards, and reaching for the object needs an attribute mypy is
        # right to say Flask does not declare.
        app = current_app if has_app_context() else None
    schemas = _component_schemas()

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
            {
                "name": "journals",
                "description": (
                    "Reading what the service wrote down. Deliberately not "
                    "under admin: the permissions are audit:view and "
                    "logs:view, which sit outside the admin resource, and "
                    "the auditor role holds them and nothing else."
                ),
            },
            {
                "name": "admin",
                "description": (
                    "Operating the service: accounts, roles and health. "
                    "Every operation is behind an admin: permission, and "
                    "each one says which."
                ),
            },
        ],
        "paths": (
            _add_security(_add_cross_cutting_responses(PATHS), app)
            if app is not None
            else _add_cross_cutting_responses(PATHS)
        ),
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
