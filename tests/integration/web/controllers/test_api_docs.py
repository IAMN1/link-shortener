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


API_PREFIX = "/api/v1"


@pytest.fixture()
def document(client):
    response = client.get("/api/openapi.json")
    assert response.status_code == 200
    return response.get_json()


class TestTheDocumentIsServed:

    def test_it_is_valid_openapi_at_the_top_level(self, document):
        assert document["openapi"].startswith("3.")
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

    def test_every_documented_verb_actually_exists(self, app, document):
        real = {}
        for rule in app.url_map.iter_rules():
            openapi_path = str(rule).replace("<", "{").replace(">", "}")
            real.setdefault(openapi_path, set()).update(
                method.lower() for method in rule.methods
            )

        for path, operations in document["paths"].items():
            for verb in operations:
                assert path in real, f"{path} is documented and does not exist"
                assert verb in real[path], f"{verb.upper()} {path} does not exist"
