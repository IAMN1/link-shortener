"""
Tests that an account's pages are marked unstorable by the real
application, not merely by a middleware in isolation.

The unit tests for ``PrivateCacheMiddleware`` install it on a bare Flask
app and set ``g.current_user`` from a query parameter, which proves the
rule and says nothing about whether the rule reaches the pages that need
it. Here the identity comes from the authentication middleware, through a
real sign-in, in an application assembled by ``create_app`` -- so a change
to the order the middlewares are installed in, or to what authentication
puts in ``g``, is caught rather than assumed away.

What it is protecting: measured before the header existed, signing out and
pressing Back redrew the previous account's dashboard from the browser's
cache -- their address and their links, with no request reaching the
service.
"""

import pytest

from tests.integration.conftest import auth_headers, register_and_login


PRIVATE = [
    "/dashboard/",
    "/dashboard/links",
    "/dashboard/stats",
    "/api/v1/links/mine",
    "/api/v1/stats/mine",
]
"""Addresses that answer with one account's own data."""

PUBLIC = [
    "/",
    "/login",
    "/api/docs",
]
"""Addresses whose answer is the same for everyone."""


class TestAnAccountsPagesAreNotStored:

    @pytest.fixture()
    def token(self, client):
        return register_and_login(client, "cache@example.com")

    @pytest.mark.parametrize("path", PRIVATE)
    def test_it_says_no_store(self, client, token, path):
        response = client.get(path, headers=auth_headers(token))

        assert response.status_code < 400, (
            f"{path} answered {response.status_code}; the check below would "
            f"pass over an error page"
        )
        assert response.headers.get("Cache-Control") == "no-store", (
            f"{path} may be stored by the browser and shown after logout"
        )


class TestPublicPagesStayCacheable:

    @pytest.mark.parametrize("path", PUBLIC)
    def test_an_anonymous_answer_is_not_marked(self, client, path):
        """
        The privacy rule has a cost, and it must not be paid where there
        is nothing to protect: these are the same bytes for every visitor.
        """
        response = client.get(path)

        assert response.status_code < 400
        assert "no-store" not in (
            response.headers.get("Cache-Control") or ""
        ), f"{path} is public and should stay cacheable"
