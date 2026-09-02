"""
What the quick-start guide tells a reader ``/api/docs`` covers.

It said "describes every endpoint". The document describes the JSON API:
measured on a running service, ``/api/openapi.json`` carried 34 paths --
33 under ``/api/v1`` and the redirect ``/{short_code}`` beside them --
and ``/health`` was not among them, while the same guide has the reader
call ``/health`` a hundred lines further down. Neither are the dashboard
pages, which is the other half of "every".

A reader who believes "every endpoint" and does not find ``/health`` there
concludes the document is stale, or that the route is not meant to be
called. Neither is so; the sentence was.

Held against the route table rather than against a number: the count moves
whenever an operation is added, and a test that has to be edited for
ordinary work is a test that gets edited without being read.
"""

from pathlib import Path

import pytest

from link_shortener.web.schemas.openapi import build_openapi


API_PREFIX = "/api/v1"

GUIDES = {
    "docs/getting-started.md": "describes every endpoint",
    "docs/getting-started.ru.md": "описывает все эндпоинты",
}
"""The claim each guide must not make, in the language it is written in.

Quoted from the English guide as it stood; the Russian one never carried
it and says "полное описание API", which is the true statement. It is
listed so that a translation of the wrong sentence would be caught on the
way in rather than a release later.
"""

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def documented_paths(app) -> set:
    """Every path the OpenAPI document declares."""
    with app.app_context():
        return set(build_openapi(base_url="http://localhost:5000").get("paths", {}))


@pytest.fixture(scope="module")
def served_rules(app) -> set:
    """Every rule the application actually answers on."""
    return {
        rule.rule for rule in app.url_map.iter_rules()
        if rule.endpoint != "static"
    }


class TestTheDocumentIsTheApiAndOnlyTheApi:

    def test_it_declares_something(self, documented_paths):
        """A guard: an empty document would pass everything below."""
        assert len(documented_paths) > 20

    def test_it_covers_the_api_and_the_redirect_beside_it(self, documented_paths):
        """
        The redirect is in the document; the correction had to say so.

        Written wrong once on the way to this file -- the guide was
        corrected to place ``/<code>`` outside the document, and this
        check is what said otherwise.
        """
        outside = sorted(p for p in documented_paths if not p.startswith(API_PREFIX))

        assert outside == ["/{short_code}"], outside

    def test_routes_exist_that_the_document_does_not_cover(self, served_rules):
        """
        The fact that makes "every endpoint" false.

        If this ever empties -- every route being under `/api/v1` and in
        the document -- the sentence would become true and the check below
        should be removed rather than worked around.
        """
        outside = {r for r in served_rules if not r.startswith(API_PREFIX)}

        assert outside, "nothing is served outside the API any more"

    def test_health_is_one_of_them(self, documented_paths, served_rules):
        """Named because the guide sends the reader to it by name."""
        assert "/health" in served_rules
        assert "/health" not in documented_paths


class TestNoGuideClaimsItCoversEverything:

    @pytest.mark.parametrize("name", sorted(GUIDES))
    def test_the_guide_does_not_overstate(self, name):
        text = (ROOT / name).read_text(encoding="utf-8")

        assert GUIDES[name] not in text, (
            f"{name} tells the reader /api/docs describes every endpoint, "
            f"and routes are served that the document does not declare"
        )
