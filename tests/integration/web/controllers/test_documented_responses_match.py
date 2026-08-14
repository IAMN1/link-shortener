"""
Every documented success response describes a body, and describes it right.

Six operations declared a status code and a sentence and no schema at all --
``/links/mine``, ``/stats/mine`` and all four ``auth`` operations -- so a
generated client got ``void`` for them, including the one that literally
answers a list of links.

Declaring a schema is only half of it: a schema nothing checks drifts from
the endpoint the first time either changes. So the answers are validated
against the models the document is generated from, on real requests through
a real application.
"""


from tests.integration.conftest import confirm_email

from link_shortener.web.schemas.auth import (
    MessageResponse, RefreshResponse, RegisterResponse, TokenPairResponse,
)
from link_shortener.web.schemas.link import ShortLinkResponse
from link_shortener.web.schemas.openapi import build_openapi
from link_shortener.web.schemas.stats import MyStatsResponse
from tests.integration.conftest import auth_headers, csrf_headers


EMAIL = "documented@example.test"
PASSWORD = "Str0ng!Passw0rd"


class TestTheDocumentDescribesABody:
    """Read from the document itself, so a new operation is covered too."""

    def test_no_success_response_is_declared_without_one(self):
        document = build_openapi("https://short.link")

        bodyless = [
            f"{verb.upper()} {path} -> {code}"
            for path, operations in document["paths"].items()
            for verb, operation in operations.items()
            for code, response in operation["responses"].items()
            if code.startswith("2") and "content" not in response
        ]

        assert bodyless == []

    def test_every_schema_referenced_is_actually_defined(self):
        """A ``$ref`` to a missing component is a document that will not
        load, and nothing else here would notice."""
        document = build_openapi("https://short.link")
        defined = set(document["components"]["schemas"])

        def refs(node):
            if isinstance(node, dict):
                if "$ref" in node:
                    yield node["$ref"].rsplit("/", 1)[-1]
                for value in node.values():
                    yield from refs(value)
            elif isinstance(node, list):
                for item in node:
                    yield from refs(item)

        assert {name for name in refs(document["paths"])} <= defined


class TestTheAnswersMatchWhatIsDocumented:
    """The half that keeps the document honest."""

    def test_registration(self, client):
        response = client.post(
            "/api/v1/auth/register", json={"email": EMAIL, "password": PASSWORD}
        )

        assert response.status_code == 202
        RegisterResponse.model_validate(response.get_json())

    def test_sign_in(self, client):
        client.post(
            "/api/v1/auth/register",
            json={"email": "signin@example.test", "password": PASSWORD},
        )
        confirm_email(client.application, "signin@example.test")

        response = client.post(
            "/api/v1/auth/login",
            json={"email": "signin@example.test", "password": PASSWORD},
        )

        assert response.status_code == 200
        TokenPairResponse.model_validate(response.get_json())

    def test_the_callers_links(self, client):
        client.post(
            "/api/v1/auth/register",
            json={"email": "links@example.test", "password": PASSWORD},
        )
        confirm_email(client.application, "links@example.test")
        token = client.post(
            "/api/v1/auth/login",
            json={"email": "links@example.test", "password": PASSWORD},
        ).get_json()["access_token"]
        headers = auth_headers(token)
        client.post(
            "/api/v1/shorten",
            json={"url": "https://example.com/documented"},
            headers=headers,
        )

        response = client.get("/api/v1/links/mine", headers=headers)

        assert response.status_code == 200
        payload = response.get_json()
        assert isinstance(payload, list)
        for item in payload:
            ShortLinkResponse.model_validate(item)

    def test_the_callers_totals(self, client):
        client.post(
            "/api/v1/auth/register",
            json={"email": "totals@example.test", "password": PASSWORD},
        )
        confirm_email(client.application, "totals@example.test")
        token = client.post(
            "/api/v1/auth/login",
            json={"email": "totals@example.test", "password": PASSWORD},
        ).get_json()["access_token"]

        response = client.get("/api/v1/stats/mine", headers=auth_headers(token))

        assert response.status_code == 200
        MyStatsResponse.model_validate(response.get_json())

    def test_a_refreshed_pair(self, client):
        """The signed-in client already carries the cookies this needs.

        It also carries the CSRF cookie, and ``/auth/refresh`` reads the
        session cookie itself, so the header has to echo it -- a bearer
        token buys no exemption on this route.
        """
        client.post(
            "/api/v1/auth/register",
            json={"email": "refresh@example.test", "password": PASSWORD},
        )
        confirm_email(client.application, "refresh@example.test")
        client.post(
            "/api/v1/auth/login",
            json={"email": "refresh@example.test", "password": PASSWORD},
        )

        response = client.post(
            "/api/v1/auth/refresh", headers=csrf_headers(client)
        )

        assert response.status_code == 200
        RefreshResponse.model_validate(response.get_json())

    def test_signing_out(self, client):
        client.post(
            "/api/v1/auth/register",
            json={"email": "logout@example.test", "password": PASSWORD},
        )
        confirm_email(client.application, "logout@example.test")
        client.post(
            "/api/v1/auth/login",
            json={"email": "logout@example.test", "password": PASSWORD},
        )

        response = client.post(
            "/api/v1/auth/logout", headers=csrf_headers(client)
        )

        assert response.status_code == 200
        MessageResponse.model_validate(response.get_json())
