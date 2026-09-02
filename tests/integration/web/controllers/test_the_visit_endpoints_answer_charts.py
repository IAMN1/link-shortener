"""
Integration tests for the endpoints the charts are drawn from.

Two things are checked here that the repository tests cannot see: what a
caller is allowed to learn, and whether the answer keeps its shape when
there is nothing to report. Both are places where a statistics endpoint
tends to be generous -- with other people's short codes, or with a
``null`` where a page expected a list.
"""

import hashlib
from datetime import datetime, time, timezone

import jwt
import pytest

from link_shortener.domain import (
    Link, LinkVisit, OriginalUrl, OwnerID, ShortCode, UrlHash,
)
from tests.integration.conftest import (
    account_with_permissions, auth_headers, ensure_user, only_this_role,
    register_and_login,
)


@pytest.fixture()
def uow_factory(app):
    """Unit of Work factory bound to the integration database."""
    with app.app_context():
        yield app.container.get_uow_factory()


def midnight(stamp):
    """
    Whether a moment on the wire falls exactly on a date.

    Parsed rather than matched as text: the response writes UTC as ``Z``
    and ``datetime.isoformat`` writes it as ``+00:00``, so a check by
    suffix passes or fails on the spelling rather than on the moment.

    Args:
        stamp: An ISO-8601 moment as the endpoint sent it.

    Returns:
        True when it is midnight.
    """
    return datetime.fromisoformat(stamp).timetz() == time(0, 0, tzinfo=timezone.utc)


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

    def test_a_span_with_no_visits_keeps_its_shape(
        self, client, uow_factory
    ):
        """
        Zeroes and a full list of buckets, not ``null`` and not ``[]``: a
        page that has to tell "nothing happened" from "no answer" ends up
        showing "Loading..." forever.

        Asked as the owner of a link nobody has opened. It used to name a
        code no link carried, which answered zeroes from an empty query
        -- but a code names somebody's link now, and one that exists is
        the honest way to ask this.
        """
        token = register_and_login(client, email="visits-empty@example.com")
        user_id = jwt.decode(token, options={"verify_signature": False})["sub"]
        link_with_visits(uow_factory, "empty1", 0, owner_id=user_id)

        body = client.get(
            "/api/v1/stats/visits?period=24h&code=empty1",
            headers=auth_headers(token),
        ).get_json()

        assert body["total"] == 0
        assert len(body["buckets"]) == 24
        assert all(bucket["total"] == 0 for bucket in body["buckets"])

    def test_a_code_no_link_carries_is_404_for_everybody(self, client):
        """The same answer the basic endpoint and the redirect give: the
        existence of a code is public, and only its traffic is not."""
        response = client.get("/api/v1/stats/visits?period=24h&code=nosuch1")

        assert response.status_code == 404
        assert response.get_json()["error"] == "LINK_NOT_FOUND"

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


class TestOneLinksTrafficIsItsOwners:
    """`?code=` names somebody's link, and its traffic is theirs.

    The service-wide answer is a count nobody owns and stays public, but
    a named code turns these endpoints into the per-link analytics that
    `can_view_link_details` exists to gate -- and they were handing them
    to anyone who could guess seven characters, while `/links/<code>`
    nulled its counters and `/links/<code>/extended` answered 401 to the
    same caller.
    """

    @pytest.mark.parametrize("path, code", [
        ("/api/v1/stats/visits?period=24h&code={code}", "secre1"),
        ("/api/v1/stats/visits/daily?days=7&code={code}", "secre2"),
    ])
    def test_an_anonymous_caller_is_refused_a_named_code(
        self, client, uow_factory, path, code
    ):
        """
        Args:
            path: The endpoint, with a place for the code.
            code: A code of its own, since the table is shared.
        """
        link_with_visits(uow_factory, code, 3, owner_id="owner-of-secret")

        response = client.get(path.format(code=code))

        assert response.status_code == 401
        assert response.get_json()["error"] == "UNAUTHENTICATED"

    @pytest.mark.parametrize("path, code", [
        ("/api/v1/stats/visits?period=24h&code={code}", "secre3"),
        ("/api/v1/stats/visits/daily?days=7&code={code}", "secre4"),
    ])
    def test_a_signed_in_stranger_is_refused_a_named_code(
        self, client, uow_factory, path, code
    ):
        """
        Args:
            path: The endpoint, with a place for the code.
            code: A code of its own, since the table is shared.
        """
        link_with_visits(uow_factory, code, 3, owner_id="owner-of-secret")
        token = register_and_login(
            client, email=f"visits-stranger-{code}@example.com"
        )

        response = client.get(
            path.format(code=code), headers=auth_headers(token)
        )

        assert response.status_code == 403
        assert response.get_json()["error"] == "FORBIDDEN"

    def test_the_owner_still_reads_their_own(
        self, client, app, uow_factory
    ):
        """The point of the check is who asks, not that nobody may ask."""
        token = register_and_login(client, email="visits-holder@example.com")
        user_id = jwt.decode(token, options={"verify_signature": False})["sub"]
        link_with_visits(uow_factory, "ownco1", 4, owner_id=user_id)

        body = client.get(
            "/api/v1/stats/visits?period=24h&code=ownco1",
            headers=auth_headers(token),
        ).get_json()

        assert body["total"] == 4

    def test_the_service_wide_answer_stays_public(self, client, uow_factory):
        """Named no code, it is a count of everything and nobody's to
        withhold -- which is what the endpoint was public for."""
        link_with_visits(uow_factory, "public1", 2)

        assert client.get(
            "/api/v1/stats/visits?period=24h"
        ).status_code == 200


class TestTheDailySeries:

    def test_it_returns_exactly_the_days_asked_for(self, client):
        """
        The off-by-one this guards against added a bucket for tomorrow.
        """
        body = client.get("/api/v1/stats/visits/daily?days=3").get_json()

        assert len(body["days"]) == 3
        today = datetime.now(timezone.utc).date()
        assert datetime.fromisoformat(body["days"][-1]["at"]).date() == today

    def test_a_bad_span_is_answered_before_a_code_nobody_may_read(
        self, client, uow_factory
    ):
        """
        What is wrong with the request, before who is asking.

        The order `decisions.md` settles for the administrative routes, and
        there is no reason for this one to differ: told "you may not read
        that link" first, a caller goes looking for a permission when what
        they have is a typo they can fix themselves. The guard on `?code=`
        was moved above this parse while closing something else, which is
        exactly how an order decided on purpose becomes an order decided by
        accident.
        """
        link_with_visits(uow_factory, "ordr01", 1, owner_id="owner-of-order")
        token = register_and_login(
            client, email="visits-order@example.com"
        )

        response = client.get(
            "/api/v1/stats/visits/daily?days=lots&code=ordr01",
            headers=auth_headers(token),
        )

        assert response.get_json()["error"] == "VALIDATION_ERROR", (
            response.get_json()
        )

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


class TestTheTwoScopesAreOpenedByTwoPermissions:
    """One address, two questions, and they are not the same grant.

    The service-wide answer is a count nobody owns and rides on
    ``stats:view_basic``, which the seeded ``guest`` role carries.
    ``scope=mine`` is the caller's own traffic and rides on
    ``link:view_own`` -- the permission the dashboard page these charts
    are drawn on is behind, and the one ``/stats/mine`` beside them asks
    for.

    Under ``stats:view_basic`` alone, seeing one's own statistics depended
    on holding the permission for the *service's*. Measured against the
    running stack before the fix: a role with ``link:view_own`` opened
    ``/dashboard/stats``, was served its tiles by ``/stats/mine``, and got
    403 from both charts on the same screen.
    """

    @pytest.fixture(scope="class")
    def own_links_only(self, app):
        """An account that may read its own links and no statistics."""
        account = account_with_permissions(
            app,
            "visits-own-only@example.com",
            "Test1234!",
            "visits-own-only",
            ["link:view_own"],
        )
        only_this_role(app, account[2], "visits-own-only")
        return account

    @pytest.fixture(scope="class")
    def service_stats_only(self, app):
        """An account that may read the service's counts and nothing of its own."""
        account = account_with_permissions(
            app,
            "visits-service-only@example.com",
            "Test1234!",
            "visits-service-only",
            ["stats:view_basic"],
        )
        only_this_role(app, account[2], "visits-service-only")
        return account

    @pytest.mark.parametrize("path", [
        "/api/v1/stats/visits?scope=mine&period=24h",
        "/api/v1/stats/visits/daily?scope=mine&days=7",
    ])
    def test_link_view_own_opens_the_callers_own_charts(
        self, own_links_only, path
    ):
        """
        Args:
            path: One of the two endpoints the page draws from. Both, since
                a caller given one chart and refused the other reads half a
                screen.
        """
        client, _, _ = own_links_only

        assert client.get(path).status_code == 200

    def test_it_does_not_open_the_service_wide_answer(self, own_links_only):
        """The other half of the rule: own is not everyone's."""
        client, _, _ = own_links_only

        response = client.get("/api/v1/stats/visits?period=24h")

        assert response.status_code == 403
        assert response.get_json()["error"] == "FORBIDDEN"

    @pytest.fixture(scope="class")
    def any_links_reader(self, app):
        """Entitled to any link's traffic, and to no count of everything."""
        account = account_with_permissions(
            app,
            "visits-any-only@example.com",
            "Test1234!",
            "visits-any-only",
            ["link:view_own", "stats:view_any"],
        )
        only_this_role(app, account[2], "visits-any-only")
        return account

    @pytest.mark.parametrize("path, code", [
        ("/api/v1/stats/visits?period=24h&code={code}", "namd01"),
        ("/api/v1/stats/visits/daily?days=7&code={code}", "namd02"),
    ])
    def test_a_named_code_carries_its_own_door(
        self, any_links_reader, uow_factory, path, code
    ):
        """
        A third question, and not the service-wide one in disguise.

        ``?code=`` is checked against that link's owner, which is what
        ``stats:view_any`` is for. Asked for ``stats:view_basic`` on top,
        the page written for exactly this reader opened and its charts did
        not: measured, ``/dashboard/links/<code>/stats`` answered 200 and
        both charts on it 403.

        Args:
            path: The endpoint, with a place for the code.
            code: A code of its own, since the table is shared.
        """
        client, _, _ = any_links_reader
        link_with_visits(uow_factory, code, 2, owner_id="owner-of-named")

        response = client.get(path.format(code=code))

        assert response.status_code == 200, response.get_json()

    def test_stats_view_basic_opens_the_service_wide_answer(
        self, service_stats_only
    ):
        client, _, _ = service_stats_only

        assert client.get(
            "/api/v1/stats/visits?period=24h"
        ).status_code == 200

    def test_it_does_not_open_the_callers_own(self, service_stats_only):
        """A count of everything is not a licence to be told about oneself.

        Not a distinction anybody would notice on the seeded roles, where
        both permissions travel together -- which is exactly why it is
        asserted rather than left to be true by accident.
        """
        client, _, _ = service_stats_only

        response = client.get("/api/v1/stats/visits?scope=mine&period=24h")

        assert response.status_code == 403
        assert response.get_json()["error"] == "FORBIDDEN"


class TestASpanDrawnInDaysIsDrawnOnTheDays:
    """Where a thirty-day answer begins, read off the endpoint itself.

    The buckets of the two long spans are a day wide and the axis under
    them is labelled with dates -- ``formatDate`` in ``charts.js``, which
    prints a date and no time. That is only honest if a bucket is a date.
    It was not: the span ran from the instant the question was asked, so a
    column labelled "8 February" held an afternoon and the morning after
    it, and the same chart on the journal page -- which had been aligned --
    was about a window nine hours away.
    """

    @pytest.mark.parametrize("period", ["30d", "90d"])
    def test_both_ends_are_midnights(self, client, period):
        """
        Args:
            period: A span whose buckets are exactly one day.
        """
        body = client.get(f"/api/v1/stats/visits?period={period}").get_json()

        assert midnight(body["since"]), body["since"]
        assert midnight(body["until"]), body["until"]

    @pytest.mark.parametrize("period", ["30d", "90d"])
    def test_every_bucket_starts_on_a_date(self, client, period):
        """The label under a column is a date; the column has to be one."""
        body = client.get(f"/api/v1/stats/visits?period={period}").get_json()

        assert body["buckets"], body
        assert all(
            midnight(bucket["at"]) for bucket in body["buckets"]
        ), body["buckets"][:3]

    @pytest.mark.parametrize("period", ["24h", "7d"])
    def test_a_shorter_bucket_keeps_the_span_as_asked(self, client, period):
        """
        "The last 24 hours" is not "yesterday and today so far".

        Args:
            period: A span whose buckets are shorter than a day.
        """
        body = client.get(f"/api/v1/stats/visits?period={period}").get_json()

        assert not midnight(body["until"]), body["until"]
