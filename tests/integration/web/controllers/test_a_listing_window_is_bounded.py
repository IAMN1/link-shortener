"""
Tests that a listing bounds the window a caller asks for.

Both listings take ``limit`` and ``offset`` off the query string, and only
one of them used to bound what it read. Measured on the running stack,
against PostgreSQL:

    GET /api/v1/admin/users?offset=-1  -> 500 INTERNAL_SERVER_ERROR
    GET /api/v1/admin/users?limit=-5   -> 500 INTERNAL_SERVER_ERROR
    GET /api/v1/links/mine?offset=-1   -> 200
    GET /api/v1/links/mine?limit=-5    -> 200

The same request, meeting two different services -- and a 500 is the wrong
answer besides: there is nothing the caller can do about it, and the
service logs an error over a request that was merely silly.

That measurement cannot be reproduced here. SQLite reads ``LIMIT -5`` as
"no limit", ``LIMIT 0`` as "nothing" and ``OFFSET -1`` as zero, so nothing
raises and a status check would pass with the bounds taken back out. What
is checked instead is the size of the answer, which the two databases agree
on: a floor of one row means one row, whatever the query string asked for.
The bounds themselves are asked of the reader directly in
``tests/unit/web/test_paging.py``.

Both routes are asked, rather than the reader alone, because a reader that
clamps correctly while a controller goes on reading the query string itself
is exactly the arrangement this replaced.
"""

import pytest

from tests.integration.conftest import account_with_permissions, auth_headers


@pytest.fixture(scope="module")
def operator(app):
    """
    An account that may read the account listing, with its own client.

    Its own, because a client that has signed in carries a session cookie
    and stops being the caller the test meant. Built once for the module:
    the application fixture is built once for the session, so registering
    the same address per test would be registering it twice.
    """
    return account_with_permissions(
        app,
        "window-operator@example.com",
        "WindowPass1!",
        "window-reader",
        ["admin:view_users"],
    )


@pytest.fixture(scope="module")
def a_second_account(app):
    """
    Somebody else in the table, so "one row" and "every row" differ.

    Without a second account a listing clamped to one row and a listing
    of the whole table are the same answer, and the check below would
    hold either way.
    """
    return account_with_permissions(
        app,
        "window-bystander@example.com",
        "WindowPass2!",
        "window-bystander",
        ["link:view_own"],
    )


class TestTheAccountListingBoundsTheWindow:

    @pytest.mark.parametrize("window, why", [
        ("limit=0", "a window of nothing is not a page"),
        ("limit=-5", "a negative window is not a page either"),
    ])
    def test_a_window_below_the_floor_answers_one_row(
        self, operator, a_second_account, window, why
    ):
        client, token, _ = operator

        response = client.get(
            f"/api/v1/admin/users?{window}", headers=auth_headers(token)
        )

        assert response.status_code == 200, response.get_json()
        assert len(response.get_json()) == 1, why

    def test_a_negative_offset_is_answered_rather_than_failed_on(
        self, operator
    ):
        """
        The measurement above, as far as SQLite can carry it: the answer
        is a listing rather than a 500. On PostgreSQL this is the whole
        finding; here it holds the route to answering at all.
        """
        client, token, _ = operator

        response = client.get(
            "/api/v1/admin/users?offset=-1", headers=auth_headers(token)
        )

        assert response.status_code == 200, response.get_json()
        assert isinstance(response.get_json(), list)


@pytest.fixture(scope="module")
def two_links(operator):
    """
    Two links owned by the operator, so a floor of one row is visible.

    Without them the listing is empty and "at most one row" holds however
    the window is read -- the check would pass with the bounds taken out,
    which is the failure mode this file exists to catch.
    """
    client, token, _ = operator
    for number in (1, 2):
        made = client.post(
            "/api/v1/shorten",
            json={"url": f"https://example.test/window-{number}"},
            headers=auth_headers(token),
        )
        assert made.status_code in (200, 201), made.get_json()
    return client, token


class TestTheLinkListingBoundsItToo:
    """The route the rule was already right on, kept honest."""

    @pytest.mark.parametrize("window", ["limit=0", "limit=-5"])
    def test_a_window_below_the_floor_holds_one_row(self, two_links, window):
        client, token = two_links

        response = client.get(
            f"/api/v1/links/mine?{window}", headers=auth_headers(token)
        )

        assert response.status_code == 200, response.get_json()
        assert len(response.get_json()) == 1, (
            "the floor is one row: nothing, or everything, is not a page"
        )


class TestTheWindowStillMeansWhatItSays:

    def test_a_window_of_one_holds_one_account(self, operator):
        client, token, _ = operator

        response = client.get(
            "/api/v1/admin/users?limit=1", headers=auth_headers(token)
        )

        assert response.status_code == 200
        assert len(response.get_json()) == 1
