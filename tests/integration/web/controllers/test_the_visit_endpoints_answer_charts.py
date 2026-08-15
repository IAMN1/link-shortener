"""
Integration tests for the endpoints the charts are drawn from.

Two things are checked here that the repository tests cannot see: what a
caller is allowed to learn, and whether the answer keeps its shape when
there is nothing to report. Both are places where a statistics endpoint
tends to be generous -- with other people's short codes, or with a
``null`` where a page expected a list.
"""

import hashlib
from datetime import datetime, timezone

import jwt
import pytest

from link_shortener.domain import (
    Link, LinkVisit, OriginalUrl, OwnerID, ShortCode, UrlHash,
)
from tests.integration.conftest import (
    account_with_permissions, auth_headers, ensure_user, register_and_login,
)


@pytest.fixture()
def uow_factory(app):
    """Unit of Work factory bound to the integration database."""
    with app.app_context():
        yield app.container.get_uow_factory()


def link_with_visits(uow_factory, code, count, owner_id=None, user_agent=None):
    """
    Store a link and a number of visits to it, all just now.

    Args:
        uow_factory: Factory for Unit of Work instances.
        code: Short code for the link.
        count: How many visits to record.
        owner_id: Account the link belongs to, if any.
        user_agent: Header the visits carry.

    Returns:
        The id of the stored link.
    """
    with uow_factory() as uow:
        if owner_id:
            ensure_user(uow._session, owner_id)
        link = Link.create(
            url_hash=UrlHash(hashlib.sha256(code.encode()).hexdigest()),
            short_code=ShortCode(code),
            original_url=OriginalUrl(f"https://example.com/{code}"),
            owner=OwnerID(owner_id) if owner_id else None,
        )
        uow.links.save(link)
        for _ in range(count):
            uow.link_visits.record(
                LinkVisit.record(link_id=link.id, user_agent=user_agent)
            )
        uow.commit()
        return link.id


class TestWhatAnAnonymousCallerGets:

    def test_the_totals_are_public_like_the_other_statistics(self, client):
        """
        The seeded guest role holds ``stats:view_basic``, and this endpoint
        answers to it -- the same decision ``/api/v1/stats`` already made.
        """
        response = client.get("/api/v1/stats/visits?period=24h")

        assert response.status_code == 200
        assert "total" in response.get_json()

    def test_the_top_links_table_is_withheld(self, client, uow_factory):
        """
        A short code is somebody's link. Counting visits is one disclosure;
        naming the links they went to is another, and it needs
        ``stats:view_full``.
        """
        link_with_visits(uow_factory, "pubtop", 3)

        body = client.get("/api/v1/stats/visits?period=24h").get_json()

        assert body["total"] >= 3
        assert body["top_links"] == []

    def test_a_span_with_no_visits_keeps_its_shape(self, client):
        """
        Zeroes and a full list of buckets, not ``null`` and not ``[]``: a
        page that has to tell "nothing happened" from "no answer" ends up
        showing "Loading..." forever.
        """
        body = client.get("/api/v1/stats/visits?period=24h&code=nosuch1").get_json()

        assert body["total"] == 0
        assert len(body["buckets"]) == 24
        assert all(bucket["total"] == 0 for bucket in body["buckets"])

    def test_an_unknown_period_is_refused_in_words(self, client):
        response = client.get("/api/v1/stats/visits?period=all-time")

        assert response.status_code == 400
        body = response.get_json()
        assert body["error"] == "VALIDATION_ERROR"
        # The refusal names what is on offer, so the caller does not have
        # to find the list somewhere else.
        assert "7d" in body["message"]

    def test_asking_for_your_own_without_signing_in_is_401(self, client):
        response = client.get("/api/v1/stats/visits?scope=mine")

        assert response.status_code == 401


class TestWhatTheOwnerAndTheAnalystGet:

    def test_scope_mine_counts_only_the_callers_links(
        self, client, app, uow_factory
    ):
        token = register_and_login(client, email="visits-owner@example.com")
        # The account's own id, taken from the token it was just issued:
        # the links have to be filed under the same account the endpoint
        # will scope to, and inventing an id would test nothing.
        user_id = jwt.decode(token, options={"verify_signature": False})["sub"]
        link_with_visits(uow_factory, "mine01", 2, owner_id=user_id)
        link_with_visits(uow_factory, "other1", 7)

        body = client.get(
            "/api/v1/stats/visits?period=24h&scope=mine",
            headers=auth_headers(token),
        ).get_json()

        assert body["total"] == 2

    def test_full_statistics_include_the_top_links(
        self, client, app, uow_factory
    ):
        _client, token, _user = account_with_permissions(
            app, "visits-analyst@example.com", "Test1234!", "visit-analyst",
            ["stats:view_basic", "stats:view_full"],
        )
        link_with_visits(uow_factory, "topful", 5)

        body = client.get(
            "/api/v1/stats/visits?period=24h", headers=auth_headers(token)
        ).get_json()

        assert any(row["label"] == "topful" for row in body["top_links"])


class TestTheDailySeries:

    def test_it_returns_exactly_the_days_asked_for(self, client):
        """
        The off-by-one this guards against added a bucket for tomorrow.
        """
        body = client.get("/api/v1/stats/visits/daily?days=3").get_json()

        assert len(body["days"]) == 3
        today = datetime.now(timezone.utc).date()
        assert datetime.fromisoformat(body["days"][-1]["at"]).date() == today

    def test_days_out_of_range_are_refused(self, client):
        assert client.get("/api/v1/stats/visits/daily?days=0").status_code == 400
        assert client.get("/api/v1/stats/visits/daily?days=9000").status_code == 400
        assert client.get("/api/v1/stats/visits/daily?days=lots").status_code == 400


class TestRobotsAreCountedAndMarked:

    def test_a_robot_shows_in_the_total_and_in_the_bot_count(
        self, client, uow_factory
    ):
        """
        Dropping robots would make this endpoint disagree with the click
        counter on the link, which counts every redirect it serves.
        """
        link_with_visits(
            uow_factory, "botcnt", 4,
            user_agent="Mozilla/5.0 (compatible; Googlebot/2.1)",
        )

        body = client.get("/api/v1/stats/visits?period=24h").get_json()

        assert body["bots"] >= 4
        assert body["total"] >= body["bots"]
