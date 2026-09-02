"""
How much of the document the contract run is still asking about.

The two live runs each carry their own size -- `smoke_test.py` holds 159
and `browser_test.py` 69, and a run that lost half its checks says so.
This directory held nothing of the kind. It generates one test per
operation, so an operation that stops being generated simply stops being
asked about, and the run stays green at whatever size it has become. CI
catches only the total loss of the directory, through pytest's exit code
5 for an empty collection.

The number is not written down here. Both halves are derived, so that a
document that gains an operation needs no edit and a document that loses
one fails:

  * every operation the service publishes is one Schemathesis loaded, and
  * every operation not loaded is one of the three this run excludes by
    name, each for the reason stated beside the exclusion.

Together those say that every published operation is either exercised by
this run or deliberately left to a test that names it -- which is the
property the missing size guard was standing in for.
"""

import re

from tests.contract.test_the_service_answers_its_own_document import (
    APP, ENDS_THE_SESSION, schema,
)


METHODS = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
)
"""The keys of a path item that are operations.

An OpenAPI path item also carries `parameters`, `summary`, `$ref` and
others, so counting its keys would count those too.
"""

EXCLUDED = re.compile(ENDS_THE_SESSION)
"""The pattern the run really excludes with, read from the run.

Not a copy. Written out here as its own literal, this file agreed with
itself: broadening the run's pattern to `^/api/v1/auth/.*$` took nine
operations out of the contract run -- six more than it believes it
excludes -- and every test below still passed.
"""


def published_operations():
    """Every (path, method) the service's own document declares."""
    document = APP.test_client().get("/api/openapi.json").get_json()
    return {
        (path, method)
        for path, item in document["paths"].items()
        for method in item
        if method in METHODS
    }


class TestTheRunSeesTheWholeDocument:

    def test_schemathesis_loaded_every_published_operation(self):
        """
        A path the loader cannot read is dropped without a word, and the
        run goes on answering for the rest.
        """
        assert len(schema) == len(published_operations())

    def test_the_document_has_operations_at_all(self):
        """The premise. Both figures above are zero if the document is
        empty, and zero equals zero."""
        assert len(published_operations()) > 30


class TestWhatIsLeftOutIsWhatWasNamed:

    def test_the_exclusion_takes_exactly_the_three_it_names(self):
        left_out = sorted(
            operation
            for operation in published_operations()
            if EXCLUDED.match(operation[0])
        )

        assert left_out == [
            ("/api/v1/auth/change-password", "post"),
            ("/api/v1/auth/logout", "post"),
            ("/api/v1/auth/refresh", "post"),
        ], left_out

    def test_the_three_are_really_in_the_document(self):
        """The other half of the premise.

        A pattern that matches nothing also "takes exactly what it
        names", and would leave this file agreeing with itself while the
        run silently covered three operations it believes it excludes --
        or, if a path were renamed, three it no longer does.
        """
        paths = {path for path, _ in published_operations()}

        for named in (
            "/api/v1/auth/logout",
            "/api/v1/auth/change-password",
            "/api/v1/auth/refresh",
        ):
            assert named in paths, named
