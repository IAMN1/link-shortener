"""
Tests that every route taking an account id answers alike when there is none.

Seven of the eight did. `GET /api/v1/admin/users/<id>/stats` answered 200
with four zeroes -- indistinguishable from a real account that has never
made a link -- because `GetUserActivityStatsUseCase` takes the id as an
argument and asks the link repository about it rather than loading the
account. Measured on the running stack against all eight, and against the
panel's page for the same id, which answered 404: two doors into one
question, disagreeing.

The table is the point of the file. A ninth route taking an id from the
address is one line here, and a route that forgets the lookup is a
failure rather than a gap nobody notices.
"""

import pytest

from tests.integration.conftest import account_with_permissions, auth_headers


GHOST = "00000000-0000-0000-0000-000000000000"

# Every administrative route that names an account in its address, with a
# body where one is required. The values need not be usable: the account
# is not there, and that is what each of these has to say.
ROUTES_TAKING_AN_ACCOUNT = [
    ("GET", f"/api/v1/admin/users/{GHOST}", None),
    ("GET", f"/api/v1/admin/users/{GHOST}/stats", None),
    ("PUT", f"/api/v1/admin/users/{GHOST}/roles", {"roles": ["user"]}),
    ("POST", f"/api/v1/admin/users/{GHOST}/activate", None),
    ("POST", f"/api/v1/admin/users/{GHOST}/deactivate", None),
    ("POST", f"/api/v1/admin/users/{GHOST}/verify-email", None),
    ("POST", f"/api/v1/admin/users/{GHOST}/resend-verification", None),
    ("DELETE", f"/api/v1/admin/users/{GHOST}", None),
]


@pytest.fixture(scope="module")
def operator(app):
    """An account that may read and manage users, with its own client."""
    return account_with_permissions(
        app,
        "asks-about-ghosts@example.test",
        "GhostPass1!",
        "asks-about-ghosts",
        ["admin:view_users", "admin:manage_users"],
    )


class TestTheApiAnswersOneWay:

    @pytest.mark.parametrize(
        "method, path, body",
        ROUTES_TAKING_AN_ACCOUNT,
        ids=[f"{m} {p.split('/')[-1]}" for m, p, _ in ROUTES_TAKING_AN_ACCOUNT],
    )
    def test_a_route_that_names_no_account_answers_404(
        self, operator, method, path, body
    ):
        client, token, _ = operator

        response = client.open(
            path, method=method, json=body, headers=auth_headers(token)
        )

        assert response.status_code == 404, response.get_json()
        assert response.get_json()["error"] == "USER_NOT_FOUND"

    def test_the_statistics_route_does_not_answer_with_zeroes(self, operator):
        """
        Named on its own because zeroes are a plausible answer: they are
        exactly what a real account with no links returns, so the failure
        this catches reads as data rather than as an error.
        """
        client, token, _ = operator

        response = client.get(
            f"/api/v1/admin/users/{GHOST}/stats", headers=auth_headers(token)
        )

        assert response.status_code != 200, (
            "a made-up id was answered with statistics"
        )


class TestThePanelAnswersTheSameWay:
    """The other door into the same question."""

    @pytest.mark.parametrize("page", ["edit", "stats"])
    def test_a_panel_page_for_no_account_answers_404(self, operator, page):
        client, token, _ = operator

        response = client.get(
            f"/dashboard/users/{GHOST}/{page}", headers=auth_headers(token)
        )

        assert response.status_code == 404
