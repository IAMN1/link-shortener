"""
Tests that the API describes itself.

``/api/docs`` rendered the landing page: the route existed, answered 200,
and told nobody anything -- the kind of gap that survives because every
check of it passes.

What is served now is generated. The request and response bodies come from
the same Pydantic models the endpoints validate against, so a field that
changes shape changes shape in the document with it; the rest -- which paths
exist, which verbs they take, what each status means -- is written once and
held against the real URL map by the last test here.
"""

import pytest
from openapi_spec_validator import validate

from link_shortener.web.schemas.openapi import OPERATION_VERBS
from tests.integration.conftest import register_and_login


def operations_of(path_item):
    """
    Yield only the keys of a path item that are operations.

    A path item may also carry ``summary``, ``description``,
    ``parameters``, ``servers`` and ``$ref``. Walking it as if every key
    were an operation is the bug these tests exist to catch in the
    generator; making it here as well would leave the tidy-up the
    generator now allows -- lifting the four copies of the short-code
    parameter to the path -- still impossible.

    Args:
        path_item: One entry of the document's ``paths``.

    Yields:
        ``(verb, operation)`` pairs.
    """
    for key, value in path_item.items():
        if key.lower() in OPERATION_VERBS:
            yield key, value


API_PREFIX = "/api/v1"


@pytest.fixture()
def cookie_session(app):
    """
    A client that has logged in and therefore carries session cookies.

    It deliberately never echoes its CSRF cookie in a header. This client
    exists to be refused: it is what a browser looks like when a page
    forgets to send the token, and what a cross-site form looks like when
    it cannot read one.
    """
    client = app.test_client()
    register_and_login(client, email="apidocs@example.com")
    return client


@pytest.fixture()
def document(client):
    response = client.get("/api/openapi.json")
    assert response.status_code == 200
    return response.get_json()


class TestTheDocumentIsServed:

    def test_a_real_validator_accepts_it(self, document):
        """Checked by a validator, not by reading back our own string.

        This test used to assert that ``openapi`` starts with ``"3."`` --
        a value the module itself sets two lines above, so it could not
        fail. Meanwhile the document was declared ``3.0.3`` and was not:
        pydantic v2 emits JSON Schema 2020-12, whose ``{"type": "null"}``
        the 3.0 Schema Object has no word for -- twenty of them in this
        document -- and the 3.0 validator refuses it with an
        ``OpenAPIValidationError`` on ``oneOf`` under
        ``components/schemas``. The declaration is ``3.1.0`` now, where
        2020-12 is the schema model, and this is what says so.
        """
        validate(document)

    def test_it_still_describes_this_service(self, document):
        """Validity is not the same as usefulness."""
        assert document["info"]["title"]
        assert document["paths"]
        assert document["components"]["schemas"]

    def test_the_page_renders_from_it(self, client):
        response = client.get("/api/docs")

        assert response.status_code == 200
        body = response.get_data(as_text=True)
        assert "/api/v1/shorten" in body
        assert "openapi.json" in body

    def test_the_page_is_no_longer_the_landing_page(self, client):
        docs = client.get("/api/docs").get_data(as_text=True)
        landing = client.get("/").get_data(as_text=True)

        assert docs != landing


class TestTheBodiesComeFromTheRealModels:

    def test_the_creation_request_carries_its_fields(self, document):
        schema = document["components"]["schemas"]["CreateShortLinkRequest"]

        assert "url" in schema["properties"]
        assert "ttl_seconds" in schema["properties"]

    def test_the_link_response_carries_its_fields(self, document):
        schema = document["components"]["schemas"]["ShortLinkResponse"]

        for field in ("short_code", "short_url", "original_url", "expires_at"):
            assert field in schema["properties"], field

    def test_the_deletion_token_is_documented(self, document):
        """It is returned once and nowhere else, so it has to be findable."""
        schema = document["components"]["schemas"]["ShortLinkResponse"]

        assert "deletion_token" in schema["properties"]

    def test_no_reference_dangles(self, document):
        """Every $ref must resolve, or a generator breaks on the document."""
        import json
        import re

        named = set(document["components"]["schemas"])
        referenced = set(
            re.findall(r'"#/components/schemas/([^"]+)"', json.dumps(document))
        )

        assert referenced <= named, f"dangling: {sorted(referenced - named)}"


class TestEveryApiRouteIsDescribed:
    """
    An endpoint added later must not be an endpoint nobody documented. The
    URL map is the authority; this list is the thing that can fall behind.
    """

    def test_no_api_route_is_missing(self, app, document):
        described = set(document["paths"])

        missing = set()
        for rule in app.url_map.iter_rules():
            path = str(rule)
            if not path.startswith(API_PREFIX):
                continue
            if path.startswith("/api/v1/admin"):
                continue  # Administration is not part of the public API.
            # Werkzeug writes <converter:name>; OpenAPI writes {name}.
            openapi_path = path.replace("<", "{").replace(">", "}")
            if openapi_path not in described:
                missing.add(openapi_path)

        assert not missing, f"undocumented endpoints: {sorted(missing)}"

    def test_every_state_changing_operation_declares_the_csrf_refusal(
        self, document
    ):
        """
        The CSRF layer answers 403 to every unsafe verb, and said so nowhere.

        A client generated from this document had no case for it: the
        refusal arrives before the request reaches any endpoint, so no
        endpoint's own list of answers was ever going to mention it.

        Bookkeeping only -- that the declaration is true of the running
        application is the next test's job, and it is the one that catches
        an endpoint being quietly let out of the CSRF layer.
        """
        from link_shortener.web.middleware.csrf import SAFE_METHODS

        undeclared = []
        for path, path_item in document["paths"].items():
            for verb, operation in operations_of(path_item):
                if verb.upper() in SAFE_METHODS:
                    continue
                if "403" not in operation["responses"]:
                    undeclared.append(f"{verb.upper()} {path}")

        assert not undeclared, f"403 undeclared on: {sorted(undeclared)}"

    def test_the_declared_csrf_refusal_is_one_the_application_gives(
        self, document, cookie_session
    ):
        """
        Every documented 403 is asked for, from a real cookie session.

        The test above cannot fail while the generator runs: it reads a key
        the generator always writes. This one drives the application. It is
        what catches an endpoint being excused from the CSRF layer --
        exempting login and registration from it, a plausible fix for a
        stale cookie answering 403, left the whole suite green and both
        operations still documented as refusing.
        """
        from link_shortener.web.middleware.csrf import SAFE_METHODS

        refused = {}
        for path, path_item in document["paths"].items():
            for verb, _ in operations_of(path_item):
                if verb.upper() in SAFE_METHODS:
                    continue
                url = path.replace("{short_code}", "nosuch")
                response = cookie_session.open(url, method=verb.upper())
                refused[f"{verb.upper()} {path}"] = response.status_code

        not_refused = {
            operation: code
            for operation, code in refused.items()
            if code != 403
        }
        assert not not_refused, f"documented 403 never happens: {not_refused}"

    def test_every_operation_declares_the_throttle_refusal(self, document):
        """
        Every route is bounded, by its own limit or by the default.

        Nine of the thirteen operations declared no 429 at all. Not the
        tightest limits -- shorten, batch, register and login declared
        theirs -- but the tightest of the nine is ten requests a minute,
        which a client meets by reading statistics twice a second.

        Declared everywhere, including where a deployment can switch it
        off: RATE_LIMIT_AUTH_DISABLED silences the four auth limits, and a
        client that cannot be refused loses nothing by handling a refusal.
        """
        undeclared = [
            f"{verb.upper()} {path}"
            for path, path_item in document["paths"].items()
            for verb, operation in operations_of(path_item)
            if "429" not in operation["responses"]
        ]

        assert not undeclared, f"429 undeclared on: {sorted(undeclared)}"

    def test_a_path_level_field_is_not_mistaken_for_an_operation(self):
        """
        A path item may carry more than operations, and did not survive it.

        `parameters`, `summary`, `description`, `servers` and `$ref` are
        all legal beside the verbs. Treating every key as an operation
        turned the obvious tidy-up -- lifting the four copies of
        CODE_PARAMETER to the path -- into a 500 from /api/openapi.json.
        """
        from link_shortener.web.schemas.openapi import (
            _add_cross_cutting_responses,
        )

        described = _add_cross_cutting_responses({
            "/x": {
                "summary": "A path, described",
                "parameters": [{"name": "q", "in": "query"}],
                "get": {"responses": {"200": {"description": "ok"}}},
            }
        })

        assert described["/x"]["summary"] == "A path, described"
        assert described["/x"]["parameters"] == [{"name": "q", "in": "query"}]
        assert "429" in described["/x"]["get"]["responses"]

    def test_a_verb_written_in_upper_case_is_still_the_same_verb(self):
        """
        A case-sensitive comparison declares a CSRF refusal on a GET.

        OpenAPI wants lower-case keys, but nothing here enforces that, and
        the failure is silent in the worst direction: the document starts
        promising a refusal on a read, which is the one place the CSRF
        layer never refuses anything.
        """
        from link_shortener.web.schemas.openapi import (
            _add_cross_cutting_responses,
        )

        described = _add_cross_cutting_responses({
            "/x": {"GET": {"responses": {"200": {"description": "ok"}}}}
        })

        assert "403" not in described["/x"]["GET"]["responses"]
        assert "429" in described["/x"]["GET"]["responses"]

    def test_the_throttle_headers_join_whatever_the_refusal_already_names(self):
        """
        Declaring one header must not cost an operation the other three.

        `setdefault` on the whole block is all-or-nothing: an operation
        whose 429 already names a header of its own would be the one left
        without Retry-After, which is the header a client actually obeys.
        """
        from link_shortener.web.schemas.openapi import (
            _add_cross_cutting_responses,
        )

        described = _add_cross_cutting_responses({
            "/x": {
                "get": {
                    "responses": {
                        "429": {
                            "description": "Slow down",
                            "headers": {"X-Quota": {"schema": {"type": "string"}}},
                        }
                    }
                }
            }
        })

        headers = described["/x"]["get"]["responses"]["429"]["headers"]
        assert "X-Quota" in headers
        assert "Retry-After" in headers

    def test_the_document_does_not_share_one_header_object_with_itself(self):
        """
        Thirteen operations must not be handed the same dict.

        The document is rebuilt on every request; a shared object edited
        through one operation is edited for all of them and for every
        document afterwards.
        """
        from link_shortener.web.schemas.openapi import build_openapi

        document = build_openapi("http://example.test")
        # The header objects, not the block holding them: merging always
        # builds a fresh outer dict, so its identity says nothing, while
        # the objects inside it are what a shared constant would leak.
        retry_after = [
            id(operation["responses"]["429"]["headers"]["Retry-After"])
            for path_item in document["paths"].values()
            for _, operation in operations_of(path_item)
        ]

        assert len(retry_after) > 1
        assert len(set(retry_after)) == len(retry_after)

    def test_folding_a_reason_in_keeps_what_the_response_already_carried(self):
        """
        The merge must not rebuild the response it is adding a reason to.

        Rebuilding it through the error helper dropped headers and replaced
        the content type, which reads as harmless only because every
        response in the table happens to be JSON with no headers today.
        """
        from link_shortener.web.schemas.openapi import (
            _add_cross_cutting_responses,
        )

        described = _add_cross_cutting_responses({
            "/x": {
                "delete": {
                    "responses": {
                        "403": {
                            "description": "Not yours",
                            "headers": {"X-Reason": {"schema": {"type": "string"}}},
                        }
                    }
                }
            }
        })

        refusal = described["/x"]["delete"]["responses"]["403"]
        assert "X-Reason" in refusal["headers"]
        assert refusal["description"].startswith("Not yours")
        assert "X-CSRF-Token" in refusal["description"]

    def test_the_header_the_document_names_is_the_header_that_is_read(
        self, document
    ):
        """
        Three places spell this header and nothing held them together.

        The middleware reads a constant, the browser code sends a literal,
        and the document prints a name in every refusal it describes.
        Renaming the constant left all of that in place: the suite stayed
        green -- both it and the live run take the name symbolically -- the
        page kept sending the old header, and a client built from the
        document kept being refused for doing exactly what it says.
        """
        from pathlib import Path

        from link_shortener.web.middleware.csrf import (
            CSRF_COOKIE_NAME, CSRF_HEADER_NAME, SAFE_METHODS
        )

        # Unsafe verbs only. A safe verb may carry a 403 of its own -- the
        # extended view refuses a caller not entitled to the traffic --
        # and that refusal has nothing to do with a token.
        descriptions = [
            operation["responses"]["403"]["description"]
            for path_item in document["paths"].values()
            for verb, operation in operations_of(path_item)
            if "403" in operation["responses"]
            and verb.upper() not in SAFE_METHODS
        ]
        assert descriptions
        for description in descriptions:
            assert CSRF_HEADER_NAME in description

        script = Path(
            "src/link_shortener/web/static/js/main.js"
        ).read_text(encoding="utf-8")
        assert f"'{CSRF_HEADER_NAME}'" in script
        assert f"{CSRF_COOKIE_NAME}=" in script

    def test_the_safe_verbs_agree_with_the_layer_that_defines_them(self):
        """
        The document's idea of "safe" is the CSRF layer's, not its own.

        Two frozensets naming the same thing drift, and the direction that
        drifts quietly is the document claiming a 403 the code never gives
        -- or omitting one it does.
        """
        from link_shortener.web.middleware.csrf import SAFE_METHODS
        from link_shortener.web.schemas.openapi import SAFE_VERBS

        assert {verb.upper() for verb in SAFE_VERBS} == set(SAFE_METHODS)

    def test_every_documented_verb_actually_exists(self, app, document):
        real = {}
        for rule in app.url_map.iter_rules():
            openapi_path = str(rule).replace("<", "{").replace(">", "}")
            real.setdefault(openapi_path, set()).update(
                method.lower() for method in rule.methods
            )

        for path, path_item in document["paths"].items():
            for verb, _ in operations_of(path_item):
                assert path in real, f"{path} is documented and does not exist"
                assert verb in real[path], f"{verb.upper()} {path} does not exist"


class TestADeclaredStatusIsOneThatCanHappen:
    """
    A status in the document is a promise about the endpoint.

    The unreachable kind is the dangerous kind: ``401`` on an endpoint that
    never asks for credentials reads as "this is protected", and a reader
    who believes it stops looking.
    """

    def test_the_service_statistics_are_reachable_without_credentials(
        self, app, document
    ):
        # Both halves, because either alone can be made true the wrong
        # way: the document could lose its 401 while the endpoint starts
        # refusing anonymous callers, or the endpoint could stay open
        # while the 401 creeps back in.
        #
        # A client of its own, never logged in. The file's `client`
        # fixture has registered and holds cookies, and a request with
        # cookies is not an anonymous request.
        anonymous = app.test_client()

        assert anonymous.get("/api/v1/stats").status_code == 200
        assert "401" not in (
            document["paths"]["/api/v1/stats"]["get"]["responses"]
        )
