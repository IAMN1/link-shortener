"""
Tests for the bounds a listing window is read within.

The rule was written twice and the two copies disagreed: the link listing
clamped what it read, the account listing passed it straight through.
Measured on the running stack before this module existed --
``GET /api/v1/admin/users?offset=-1`` answered 500 while
``GET /api/v1/links/mine?offset=-1`` answered 200.

The ceiling is checked here rather than through a route because proving it
end to end would mean storing two hundred and one rows to see two hundred
come back, which buys nothing the direct question does not.
"""

import pytest
from flask import Flask

from link_shortener.web.paging import MAX_PAGE_SIZE, window_from_query


@pytest.fixture()
def asking():
    """Ask the reader what it makes of a query string."""
    app = Flask(__name__)

    def read(query, default_limit=50, **kwargs):
        with app.test_request_context(f"/?{query}"):
            return window_from_query(default_limit, **kwargs)

    return read


class TestWhatTheCallerAsksFor:

    def test_a_window_inside_the_bounds_is_taken_as_asked(self, asking):
        assert asking("limit=25&offset=75") == (25, 75)

    def test_an_absent_window_is_the_listing_s_own_default(self, asking):
        assert asking("", default_limit=100) == (100, 0)

    def test_a_value_that_is_not_a_number_falls_back(self, asking):
        """
        ``type=int`` hands back the fallback rather than raising, which
        is what both listings already did with ``?limit=all``.
        """
        assert asking("limit=all&offset=none", default_limit=50) == (50, 0)


class TestWhatTheCallerDoesNotGetToAskFor:

    @pytest.mark.parametrize("query, why", [
        ("offset=-1", "a negative OFFSET is not a query PostgreSQL runs"),
        ("limit=-5", "nor a negative LIMIT"),
        ("limit=0", "a window of nothing is not a page"),
    ])
    def test_a_window_below_the_floor_is_lifted_to_it(self, asking, query, why):
        limit, offset = asking(query)

        assert limit >= 1, why
        assert offset >= 0, why

    def test_a_window_above_the_ceiling_is_brought_down_to_it(self, asking):
        """``?limit=100000000`` was a request for the whole table at once."""
        limit, _ = asking("limit=100000000")

        assert limit == MAX_PAGE_SIZE

    def test_a_listing_may_set_a_lower_ceiling_of_its_own(self, asking):
        limit, _ = asking("limit=500", max_limit=10)

        assert limit == 10
