"""
The published document says which operations take a token, and which need one.

``components.securitySchemes.bearerAuth`` was declared and almost nothing
referenced it. Measured on the document the service itself serves: of **39**
operations, **two** carried a ``security`` key, and **34** of the rest listed
``401`` or ``403`` among their own responses -- a document telling a reader
that a call needs no credentials and answers "unauthenticated".

What that costs is not theoretical. An operation with no ``security`` is one
Swagger UI sends no ``Authorization`` header for, so *Try it out* on every
admin route answered 401 with the Authorize box filled in; and a client
generated from the document -- which is what a document is for -- has no
place to put a token on those calls.

The answer is computed from the routes rather than typed into the table:
``require_permission`` leaves the permission it enforces on the view,
``login_required`` and ``requires_credentials`` mark the two kinds of route
that decide for themselves, and ``guest`` -- the role an anonymous caller
acts under -- decides whether a token is *required* or merely *accepted*.
A list typed beside the routes is a list that stops agreeing with them.
"""

import pytest

from link_shortener.web.schemas.openapi import (
    OPERATION_VERBS,
    as_documented_path,
    build_openapi,
)


BEARER = {"bearerAuth": []}


def operations(document):
    """Every operation in the document, as (where, verb, body)."""
    found = []
    for path, verbs in document["paths"].items():
        for verb, operation in verbs.items():
            if verb in OPERATION_VERBS and isinstance(operation, dict):
                found.append((path, verb, operation))
    return found


@pytest.fixture(scope="module")
def document(app):
    """The document as the service assembles it, routes and all."""
    with app.app_context():
        return build_openapi(base_url="http://localhost:5000")


class TestTheSweepHasSomethingToSweep:

    def test_the_document_describes_the_api(self, document):
        assert len(operations(document)) >= 38

    def test_the_scheme_is_declared(self, document):
        schemes = document["components"]["securitySchemes"]

        assert schemes["bearerAuth"]["type"] == "http"
        assert schemes["bearerAuth"]["scheme"] == "bearer"


AUTHENTICATION = "/api/v1/auth/"
"""Where a 401 is about the request, spelled here rather than imported.

``openapi.py`` exempts the same prefix, and reading its constant would
have made this test agree with the code by construction: whatever the
exemption grew to cover, the check would have skipped exactly that and
reported nothing. Written out, the two are two statements, and a widened
exemption in the code makes them disagree.

This was a frozenset of nine operations on both sides, which is the same
fault with a shorter reach: a tenth ``/auth`` route would have been
skipped by neither, so the check would have caught it -- but only after
somebody wrote it into both places.
"""


class TestEveryOperationSaysSomething:
    """
    Silence is not "no credentials" by accident -- it says exactly that.

    An operation with no ``security`` key inherits the document's, and this
    document declares none globally. So an omission reads as "open", which
    is what 34 guarded operations were saying.
    """

    def test_none_is_left_to_inference(self, document):
        silent = [
            f"{verb.upper()} {path}"
            for path, verb, operation in operations(document)
            if "security" not in operation
        ]

        assert not silent, f"operations declaring nothing: {silent}"


class TestARefusalACredentialCanChangeSaysSo:
    """
    If a token can turn the answer, the document has to offer somewhere to
    put one -- required where anonymous callers cannot pass at all, optional
    where the same call serves both.
    """

    def test_every_401_outside_auth_admits_a_token(self, document):
        mute = []
        for path, verb, operation in operations(document):
            if path.startswith(AUTHENTICATION):
                continue
            refuses = {"401", "403"} & set(operation.get("responses", {}))
            if refuses and BEARER not in operation.get("security", []):
                mute.append(f"{verb.upper()} {path} answers {sorted(refuses)}")

        assert not mute, (
            "these refuse a caller and never say a token belongs: " + str(mute)
        )

    def test_signing_in_needs_no_token(self, document):
        """
        The other side, and the reason the list above is a list.

        ``/auth/login`` answers 401 because the password is wrong. Asking a
        client to hold a token before it can get one would be a document
        describing a service nobody can start using.
        """
        login = document["paths"]["/api/v1/auth/login"]["post"]

        assert login["security"] == []


class TestItAgreesWithTheRoutesThemselves:
    """
    The document is checked against the code it describes, not against a
    copy of the same opinion.
    """

    def test_a_guarded_operation_requires_a_token(self, app, document):
        """
        Guarded by a permission ``guest`` does not hold -- an anonymous
        caller cannot pass, so the token is required rather than accepted.
        """
        from link_shortener.web.schemas.openapi import _anonymous_may

        with app.app_context():
            anonymous_may = _anonymous_may(app)
            assert anonymous_may("link:create"), (
                "the authorization service could not be asked, so this "
                "check would pass by having nothing to compare"
            )

            guarded = [
                (rule, getattr(app.view_functions.get(rule.endpoint),
                               "required_permission", None))
                for rule in app.url_map.iter_rules()
            ]
            guarded = [
                (rule, permission) for rule, permission in guarded
                if permission is not None and not anonymous_may(permission)
            ]

        wrong = []
        for rule, permission in guarded:
            described = document["paths"].get(as_documented_path(str(rule)))
            if not described:
                continue
            for method in (rule.methods or set()):
                operation = described.get(method.lower())
                if not isinstance(operation, dict):
                    continue
                if operation.get("security") != [BEARER]:
                    wrong.append(
                        f"{method} {rule} needs {permission} but declares "
                        f"{operation.get('security')}"
                    )

        assert not wrong, wrong

    def test_an_operation_a_guest_may_use_only_accepts_one(self, app, document):
        """
        The half that keeps "required" meaningful.

        ``POST /api/v1/shorten`` is the service's whole point for anonymous
        callers, and a document demanding a token for it would be wrong in
        the direction that costs users.
        """
        shorten = document["paths"]["/api/v1/shorten"]["post"]

        assert {} in shorten["security"], shorten["security"]
        assert BEARER in shorten["security"], shorten["security"]

    def test_the_journals_require_one(self, document):
        """
        No decorator names their permission -- the journal asked for does --
        so they are the case the marker exists for.
        """
        for path in ("/api/v1/journals/{journal}", "/api/v1/journals/counters"):
            assert document["paths"][path]["get"]["security"] == [BEARER], path


class TestTheServedDocumentCarriesIt:
    """
    Built in a request, which is the only way anybody actually gets it.

    The routes are what decide, so a document assembled without them would
    be a different document -- and this is the one that reaches clients.
    """

    def test_the_endpoint_answers_with_security_on_admin_operations(self, app):
        served = app.test_client().get("/api/openapi.json")

        assert served.status_code == 200
        admin = served.get_json()["paths"]["/api/v1/admin/users"]["get"]
        assert admin["security"] == [BEARER]
