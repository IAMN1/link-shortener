"""An operation that reads a request body is an operation that describes one.

``test_api_docs`` holds that every route is in the document and
``test_the_document_declares_what_the_routes_answer`` holds that every
status it gives is declared. Neither looked at the request, and nine
operations went the whole way undescribed: every ``/api/v1/auth/`` route
that takes a body read it as a dictionary, so ``/api/openapi.json`` named
nine endpoints a generated client could reach and not one it could fill in.

Why the sweep is transitive rather than a look at each view function: a
handler may read the body through a helper of its own module --
``_read_credentials`` and ``_read_refresh_token`` both do -- and a check
that reads only the view function's own source finds five of the nine and
reports the other four as fine. The walk follows calls into the module the
handler is defined in, which is as far as any of them reaches.

Only unsafe verbs are swept. A GET carrying a body is undefined in HTTP and
described nowhere in this document: ``GET /api/v1/auth/verify`` shares a
function with the POST and reads the body under a check on the method, and
attributing that read to the GET would demand a body the route takes as a
query parameter.
"""

import ast
import inspect
import re
import sys
import textwrap

import pytest

from link_shortener.web.schemas.openapi import build_openapi


# Every name that means "this function read the request body". The first
# three are ``web/request_body.py``'s, which is where the application reads
# a body; ``get_json`` is Flask's own, for a controller that goes direct.
BODY_READERS = frozenset({
    "json_object", "optional_json_object", "decoded_body", "get_json",
})

# Attributes of ``request`` that are the body by another name.
BODY_ATTRIBUTES = frozenset({"json", "form", "data", "files"})

SAFE_VERBS = frozenset({"get", "head", "options", "trace"})


def _openapi_path(rule):
    """Flask spells a path parameter ``<path:journal>``; OpenAPI ``{journal}``."""
    return re.sub(r"<(?:[^:<>]+:)?([^<>]+)>", r"{\1}", rule)


def _functions_of(module):
    """Every function a module defines, by name, for the walk to step into."""
    try:
        source = inspect.getsource(module)
    except (OSError, TypeError):  # pragma: no cover - a C or generated module
        return {}
    return {
        node.name: node for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _called_name(node):
    """The bare name of whatever is being called, or None."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def reads_body(function, seen=None):
    """
    Say how a function reaches the request body, or None if it does not.

    Args:
        function: The function to walk.
        seen: Names already walked, so that mutual recursion terminates.

    Returns:
        A string naming the read, for a failure message that says where to
        look, or None.
    """
    seen = set() if seen is None else seen
    name = (getattr(function, "__module__", None),
            getattr(function, "__qualname__", None))
    if name in seen:
        return None
    seen.add(name)

    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    except (OSError, TypeError, SyntaxError):  # pragma: no cover
        return None

    module = sys.modules.get(function.__module__)
    neighbours = _functions_of(module) if module else {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                and node.value.id == "request" and node.attr in BODY_ATTRIBUTES:
            return f"request.{node.attr}"
        if not isinstance(node, ast.Call):
            continue
        called = _called_name(node.func)
        if called in BODY_READERS:
            return f"{called}()"
        if called in neighbours and called != getattr(function, "__name__", None):
            helper = getattr(module, called, None)
            deeper = reads_body(helper, seen) if helper is not None else None
            if deeper:
                return f"{called}() -> {deeper}"
    return None


def _handler_of(app, endpoint):
    """The function under whatever decorators the route was registered with."""
    handler = app.view_functions[endpoint]
    while hasattr(handler, "__wrapped__"):
        handler = handler.__wrapped__
    return handler


@pytest.fixture(scope="module")
def document():
    """The published document, built the way the route serves it."""
    return build_openapi("https://short.link")


class TestEveryBodyTheRoutesReadIsDescribed:

    def test_each_reading_operation_declares_a_request_body(self, app, document):
        undescribed = []
        checked = 0

        for rule in app.url_map.iter_rules():
            operations = document["paths"].get(_openapi_path(str(rule)), {})
            handler = _handler_of(app, rule.endpoint)
            read = reads_body(handler)
            if not read:
                continue
            for verb in sorted(rule.methods - {"HEAD", "OPTIONS"}):
                operation = operations.get(verb.lower())
                if operation is None or verb.lower() in SAFE_VERBS:
                    continue
                checked += 1
                if "requestBody" not in operation:
                    undescribed.append(
                        f"{verb} {rule} reads the body through {read} and "
                        f"describes no requestBody"
                    )

        assert checked >= 14, f"only {checked} body-reading operations were swept"
        assert undescribed == []

    def test_every_described_body_names_a_schema_the_document_carries(
        self, document
    ):
        """A ``$ref`` to a component that is not there is a client that cannot build."""
        components = document["components"]["schemas"]
        dangling = []

        for path, item in document["paths"].items():
            for verb, operation in item.items():
                body = operation.get("requestBody") if isinstance(operation, dict) else None
                if not body:
                    continue
                schema = body["content"]["application/json"]["schema"]
                name = schema["$ref"].rsplit("/", 1)[-1]
                if name not in components:
                    dangling.append(f"{verb.upper()} {path} -> {name}")

        assert dangling == []
