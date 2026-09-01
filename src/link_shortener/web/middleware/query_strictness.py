"""
An undeclared query parameter is refused, on the API and nowhere else.

``StrictRequest`` closed this door for request bodies: a field the service
does not declare is refused rather than ignored, because "the service
accepts a field, answers 201, and does nothing with it" is the one answer a
caller cannot tell from success. The sentence that argued for it named a
query string as the case that started it -- ``?short_code=`` where the
parameter is ``code`` answering with service-wide figures instead of one
link's -- and a model validates a body, so the case it named stayed open.
Measured on a live stack afterwards: ``GET
/api/v1/stats/visits?short_code=<code>`` returned the whole service's
counts, byte for byte the same answer as ``GET /api/v1/stats/visits`` with
nothing at all, while ``?code=<code>`` returned that link's.

**What decides.** The published OpenAPI document, which already declares
every operation's parameters and is already held against the route table.
One source of truth rather than a second list beside the first: a table of
allowed names kept next to the document is a table that stops agreeing with
it, quietly, on the day somebody adds a parameter.

**Where it applies, and where it does not.** Under ``/api/v1`` only. A page
is reached by navigation, and navigation carries whatever the address bar
was given -- a tracking parameter from a mail client, an anchor a search
engine added. Refusing those would break arrivals that have nothing to do
with this service, so pages read what they know and ignore the rest, which
for them is right. An API caller assembles its own URL and gets no such
allowance.

**An operation the document does not describe is left alone.** The
alternative -- refusing every parameter for it -- turns a gap in the
document into refusals on a working route. That the document describes
every operation is somebody else's test.
"""

from typing import Dict, FrozenSet, Optional, Set, Tuple

from flask import Flask, request

from link_shortener.domain.exceptions import ValidationError
from link_shortener.domain.i18n import N_
from link_shortener.web.schemas.openapi import (
    as_documented_path,
    documented_paths,
)


API_PREFIX = "/api/v1"
"""The only paths this applies to, and the reason is in the module docstring."""

def declared_query_parameters(app: Flask) -> Dict[Tuple[str, str], FrozenSet[str]]:
    """
    What each API operation says it accepts in the query string.

    Built once, at start-up. The document costs a few milliseconds to
    assemble and this needs it on every request; building it per request
    was measured at 4.08 ms for the endpoint that serves it.

    Args:
        app: The application whose routes are being described.

    Returns:
        ``{(rule, METHOD): {names}}`` for every operation the document
        describes. An operation missing from the document is missing from
        here, and is therefore not checked.
    """
    # The table rather than the assembled document: this needs one field
    # of it, and assembling the whole thing costs about 4 ms -- most of it
    # generating component schemas that are thrown away here. The two
    # passes that finish the document write `responses` and `security`, so
    # the parameters are the same either way; measured across all 23
    # operations that declare one.
    paths = documented_paths()

    declared: Dict[Tuple[str, str], FrozenSet[str]] = {}
    for rule in app.url_map.iter_rules():
        template = str(rule)
        if not template.startswith(API_PREFIX):
            continue
        operations = paths.get(as_documented_path(template))
        if not operations:
            continue
        for method in rule.methods or set():
            operation = operations.get(method.lower())
            if not isinstance(operation, dict):
                continue
            names: Set[str] = {
                parameter["name"]
                for parameter in operation.get("parameters", [])
                if parameter.get("in") == "query"
            }
            declared[(template, method)] = frozenset(names)
    return declared


class QueryStrictnessMiddleware:
    """
    Refuses a query parameter the operation never declared.

    Attributes:
        app: The application this is installed on.
        declared: What each operation accepts, read once at start-up.
    """

    def __init__(self, app: Flask):
        """
        Args:
            app: The application to install the check on.
        """
        self.app = app
        self._declared: Optional[Dict[Tuple[str, str], FrozenSet[str]]] = None
        self._register_handler()

    @property
    def declared(self) -> Dict[Tuple[str, str], FrozenSet[str]]:
        """
        What each operation accepts, read from the document once.

        Built on the first request rather than in ``__init__``. The
        middleware is installed before the blueprints are registered, so at
        construction time ``url_map`` holds almost no routes -- built
        there, this map came out empty and every undeclared parameter went
        through exactly as before, with the check installed and the tests
        red. A ``before_request`` hook runs when the application is whole,
        which is the earliest moment the answer is right.

        Returns:
            The map, assembled once and kept.
        """
        if self._declared is None:
            self._declared = declared_query_parameters(self.app)
        return self._declared

    def _allowed(self) -> Optional[FrozenSet[str]]:
        """
        The names this request's operation accepts, if it is described.

        Returns:
            The set of accepted names, or ``None`` when this request is not
            one this check speaks for -- a page, or an operation the
            document does not describe.
        """
        rule = request.url_rule
        if rule is None or not str(rule).startswith(API_PREFIX):
            return None
        return self.declared.get((str(rule), request.method))

    def _register_handler(self) -> None:
        """Install the check ahead of every view."""

        @self.app.before_request
        def refuse_undeclared_query_parameters():
            allowed = self._allowed()
            if allowed is None:
                return None

            undeclared = sorted(set(request.args.keys()) - allowed)
            if not undeclared:
                return None

            # The first name only. A caller fixing a request fixes one
            # thing at a time, and the whole list of what they got wrong
            # is also a list of what the service does not have.
            raise ValidationError(
                f"'{undeclared[0]}' is not a parameter of this endpoint",
                field=undeclared[0],
                template=N_("'%(name)s' is not a parameter of this endpoint"),
                params={"name": undeclared[0]},
            )
