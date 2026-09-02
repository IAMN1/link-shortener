"""
The two routes that take an account out of service and put it back.

Deactivation was reached end to end by the suite; activation was not.
Measured by ``coverage report`` over the administrative perimeter before
this file existed: ``UserManagementService.activate_user`` was untouched
in full, and so was ``AdminService.activate_user`` -- while
``ActivateUserUseCase`` and ``AdminApiController`` both stood at 100%.
Every one of those runs came through a mock: the controller test replaces
the facade, and the guard tests ask the route only for a 403.

So ``POST /api/v1/admin/users/<id>/activate`` was answered by nothing but
the live run, and a regression anywhere below the use case -- a service
that no longer saves, an entity that no longer flips the flag -- would
have left the suite green.

The pair is checked together on purpose. What makes activation worth
having is that it undoes deactivation, and the two halves are only worth
as much as the state they leave behind: the account can sign in again.
"""

import pytest
from sqlalchemy import text

from tests.integration.conftest import (
    account_with_permissions, auth_headers, confirm_email,
)


PASSWORD = "Test1234!"


@pytest.fixture(scope="module")
def operator(app):
    """An account that may manage users, and read them back."""
    return account_with_permissions(
        app,
        "switches-accounts@example.test",
        PASSWORD,
        "switches-accounts",
        ["admin:manage_users", "admin:view_users"],
    )


@pytest.fixture()
def subject(app):
    """
    A confirmed, active account for the routes to act on.

    Confirmed because the point of the pair is whether the account can
    sign in, and an unconfirmed one cannot for a different reason.
    """
    email = "switched@example.test"
    client = app.test_client()
    client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    # The suite's own helper rather than an UPDATE written here: it binds
    # ``True`` rather than ``1``, and the comment beside it says why --
    # SQLite takes either, PostgreSQL refuses the integer for a boolean
    # column. Registration already leaves the account active, so the flag
    # this file is about needs no setting up.
    confirm_email(app, email)

    with app.app_context():
        with app.container.get_db_manager().session() as session:
            row = session.execute(
                text("SELECT id, is_active FROM users WHERE email = :e"),
                {"e": email},
            ).fetchone()
    assert row is not None and row[1], "the account did not start out active"

    yield row[0], email

    with app.app_context():
        with app.container.get_db_manager().session() as session:
            session.execute(
                text("DELETE FROM users WHERE email = :e"), {"e": email}
            )
            session.commit()


def stored_state(app, email):
    """Whether the stored row says the account is active."""
    with app.app_context():
        with app.container.get_db_manager().session() as session:
            row = session.execute(
                text("SELECT is_active FROM users WHERE email = :e"),
                {"e": email},
            ).fetchone()
    return bool(row[0])


def signs_in(app, email):
    """Whether the account can sign in, which is what the flag decides."""
    response = app.test_client().post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    return response.status_code == 200


class TestTakingAnAccountOutOfServiceAndBack:

    def test_deactivating_stops_the_account_signing_in(self, app, operator, subject):
        client, token, _ = operator
        user_id, email = subject
        assert signs_in(app, email), "the account was not usable to begin with"

        response = client.post(
            f"/api/v1/admin/users/{user_id}/deactivate",
            headers=auth_headers(token),
        )

        assert response.status_code == 200, response.get_json()
        assert response.get_json()["is_active"] is False
        assert stored_state(app, email) is False
        assert not signs_in(app, email)

    def test_activating_lets_it_sign_in_again(self, app, operator, subject):
        """
        The route the suite reached only through a mock. The answer, the
        stored row and the login are all asked, because the use case can
        return a cheerful DTO over a service that saved nothing.
        """
        client, token, _ = operator
        user_id, email = subject
        client.post(
            f"/api/v1/admin/users/{user_id}/deactivate",
            headers=auth_headers(token),
        )
        assert stored_state(app, email) is False, "setup did not take"

        response = client.post(
            f"/api/v1/admin/users/{user_id}/activate",
            headers=auth_headers(token),
        )

        assert response.status_code == 200, response.get_json()
        assert response.get_json()["is_active"] is True
        assert stored_state(app, email) is True
        assert signs_in(app, email)

    def test_activating_an_account_that_is_not_there_is_a_404(
        self, operator
    ):
        """The branch under the flag: no account, no state to change."""
        client, token, _ = operator

        response = client.post(
            "/api/v1/admin/users/00000000-0000-0000-0000-000000000000/activate",
            headers=auth_headers(token),
        )

        assert response.status_code == 404, response.get_json()
        assert response.get_json()["error"] == "USER_NOT_FOUND"
