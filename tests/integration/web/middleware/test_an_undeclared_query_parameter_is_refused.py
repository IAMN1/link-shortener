"""
A query parameter the operation never declared is refused, not ignored.

``StrictRequest`` closed this for request bodies, and the sentence that
argued for it named a query string as the case that started it: a mistyped
``?short_code=`` where the parameter is ``code``, answering ``200`` with
service-wide figures instead of one link's. A model validates a body, so
the case it named went on happening. Measured on a live stack before this
was written:

    GET /api/v1/stats/visits?code=<code>        -> that link's figures
    GET /api/v1/stats/visits?short_code=<code>  -> the whole service's
    GET /api/v1/stats/visits                    -> the same, byte for byte

The caller who wrote ``short_code`` got an answer that looked like theirs
and was not, with nothing to tell them apart.

What decides is the published OpenAPI document, which already declares
each operation's parameters. The two properties that matter are separated
below: that a declared parameter still works (so this cannot be "fixed" by
refusing everything) and that an undeclared one no longer does.

Pages are deliberately outside it. A browser arrives carrying whatever was
in the address bar -- a tracking parameter, an anchor a mail client added --
and refusing those would break arrivals that have nothing to do with this
service.
"""

import pytest

from tests.integration.conftest import auth_headers, csrf_headers
from tests.integration.web.middleware.test_authentication import (
    _register_and_get_tokens,
)


@pytest.fixture(scope="module")
def owner(app):
    """An account with one link, and the code of that link."""
    client = app.test_client()
    access, _ = _register_and_get_tokens(client, "query-strict@example.com")
    made = client.post(
        "/api/v1/shorten",
        json={"url": "https://example.com/query-strictness"},
        headers=csrf_headers(client),
    )
    assert made.status_code == 201, made.get_data(as_text=True)[:200]
    return access, made.get_json()["short_code"]


class TestTheCaseThatStartedIt:

    def test_the_declared_spelling_answers_for_the_link(self, app, owner):
        access, code = owner

        with app.test_client() as caller:
            r = caller.get(
                "/api/v1/stats/visits",
                query_string={"code": code},
                headers=auth_headers(access),
            )

        assert r.status_code == 200

    def test_the_mistyped_one_is_refused(self, app, owner):
        access, code = owner

        with app.test_client() as caller:
            r = caller.get(
                "/api/v1/stats/visits",
                query_string={"short_code": code},
                headers=auth_headers(access),
            )

        assert r.status_code == 400
        body = r.get_json()
        assert body["error"] == "VALIDATION_ERROR"
        assert "short_code" in body["message"]

    def test_it_no_longer_answers_the_same_as_asking_nothing(self, app, owner):
        """
        The property behind the refusal.

        The defect was not the status. It was that two different questions
        -- "this link" and "everything" -- came back as one answer, and the
        caller could not see which they had asked.
        """
        access, code = owner

        with app.test_client() as caller:
            everything = caller.get(
                "/api/v1/stats/visits", headers=auth_headers(access)
            )
            mistyped = caller.get(
                "/api/v1/stats/visits",
                query_string={"short_code": code},
                headers=auth_headers(access),
            )

        assert everything.status_code == 200
        assert mistyped.status_code != everything.status_code


class TestDeclaredParametersStillWork:
    """So the check cannot be satisfied by refusing everything."""

    @pytest.mark.parametrize("path,params", [
        ("/api/v1/links/mine", {"limit": 5, "offset": 0}),
        ("/api/v1/stats/visits", {"period": "7d", "scope": "service"}),
        ("/api/v1/stats/visits/daily", {"days": 7, "scope": "service"}),
    ])
    def test_a_documented_parameter_is_accepted(self, app, owner, path, params):
        access, _ = owner

        with app.test_client() as caller:
            r = caller.get(path, query_string=params, headers=auth_headers(access))

        assert r.status_code == 200

    def test_no_parameters_at_all_is_still_fine(self, app, owner):
        access, _ = owner

        with app.test_client() as caller:
            r = caller.get("/api/v1/links/mine", headers=auth_headers(access))

        assert r.status_code == 200


class TestOnOperationsThatDeclareNone:

    def test_an_invented_parameter_is_refused(self, app, owner):
        access, _ = owner

        with app.test_client() as caller:
            r = caller.get(
                "/api/v1/stats",
                query_string={"nonsense": "1"},
                headers=auth_headers(access),
            )

        assert r.status_code == 400

    def test_the_same_call_without_it_is_not(self, app, owner):
        access, _ = owner

        with app.test_client() as caller:
            r = caller.get("/api/v1/stats", headers=auth_headers(access))

        assert r.status_code == 200


class TestPagesAreLeftAlone:
    """
    A page is reached by navigation, which carries what it carries.

    Held so that somebody tightening this later has to decide about
    arrivals on purpose rather than by widening a prefix.
    """

    @pytest.mark.parametrize("path", ["/", "/login"])
    def test_an_unknown_parameter_does_not_stop_a_page_opening(self, app, path):
        with app.test_client() as visitor:
            r = visitor.get(path, query_string={"utm_source": "a-newsletter"})

        assert r.status_code == 200
