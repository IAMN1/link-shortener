"""
Tests that a request naming one role twice is answered as one role.

What a request carries is the set an account is to wear; naming a role
twice does not name two roles. Before this, the repeat reached the
association table as two identical rows, the primary key refused them, and
the refusal came back as somebody else's:

    PUT /api/v1/admin/users/<id>/roles  {"roles": ["user", "user"]}
      -> 409 EMAIL_ALREADY_REGISTERED  "Email already registered"

measured on the running stack, for a request that carries no address at
all. ``SQLAlchemyUserRepository.save`` caught every ``IntegrityError`` its
flush could raise and declared each one a taken address -- and that flush
writes the role associations as well as the account.

Two things came of it, and both are checked here: the repeat is now
collapsed where role names are resolved, so the request simply works, and
the catch is narrowed to the address index, so a violation that is not
about the address is not answered as though it were.

SQLite does not refuse the duplicate association at all, so the 409 itself
cannot be reproduced by the suite; what is held here is the behaviour that
replaced it -- one role on the account, and an answer that says so.
"""

import pytest
from sqlalchemy import text

from tests.integration.conftest import account_with_permissions, auth_headers


PASSWORD = "Repeated1!"


@pytest.fixture(scope="module")
def operator(app):
    """
    An account that may create users and set their roles.

    Carries what the `analyst` role grants as well, because nobody
    confers what they do not hold: the checks below hand out `user` and
    `analyst`, and the registration this fixture builds on already
    supplies the `user` half.
    """
    return account_with_permissions(
        app,
        "repeats-roles@example.test",
        PASSWORD,
        "repeats-roles",
        [
            "admin:manage_users",
            "admin:view_users",
            "stats:view_any",
            "stats:view_full",
        ],
    )


def associations(app, user_id):
    """How many rows the association table holds for this account."""
    with app.app_context():
        with app.container.get_db_manager().session() as session:
            return session.execute(
                text("SELECT COUNT(*) FROM user_roles WHERE user_id = :u"),
                {"u": user_id},
            ).scalar()


class TestCreatingAnAccountWithARepeatedRole:

    def test_the_account_is_created(self, app, operator):
        client, token, _ = operator

        response = client.post(
            "/api/v1/admin/users",
            json={
                "email": "made-with-repeats@example.test",
                "password": PASSWORD,
                "roles": ["user", "user"],
            },
            headers=auth_headers(token),
        )

        assert response.status_code == 201, response.get_json()

    def test_the_answer_names_the_role_once(self, app, operator):
        """
        The answer used to list the role twice while the table held it
        once, so the account it described was not the account stored.
        """
        client, token, _ = operator

        response = client.post(
            "/api/v1/admin/users",
            json={
                "email": "answered-once@example.test",
                "password": PASSWORD,
                "roles": ["user", "user"],
            },
            headers=auth_headers(token),
        )

        assert response.status_code == 201, response.get_json()
        assert response.get_json()["roles"] == ["user"]
        assert associations(app, response.get_json()["id"]) == 1


class TestReplacingRolesWithARepeatedOne:

    @pytest.fixture()
    def account(self, operator, request):
        """
        An account to set roles on, one per test.

        The address carries the test's name because the application
        fixture is built once for the session: a single address would be
        registered by the first test and refused for the second.
        """
        client, token, _ = operator
        made = client.post(
            "/api/v1/admin/users",
            json={
                "email": f"{request.node.name[:40]}@example.test",
                "password": PASSWORD,
            },
            headers=auth_headers(token),
        )
        assert made.status_code == 201, made.get_json()
        return made.get_json()["id"]

    def test_the_request_is_answered_and_not_refused(
        self, app, operator, account
    ):
        client, token, _ = operator

        response = client.put(
            f"/api/v1/admin/users/{account}/roles",
            json={"roles": ["analyst", "analyst"]},
            headers=auth_headers(token),
        )

        assert response.status_code == 200, response.get_json()
        assert response.get_json()["roles"] == ["analyst"]
        assert associations(app, account) == 1

    def test_a_refusal_would_not_have_been_about_an_address(
        self, app, operator, account
    ):
        """
        The shape of the old failure, kept as a check of its own: whatever
        this route answers, it is not the address error. Nothing in the
        request carries an address, and an answer that names one sends the
        caller looking in the wrong place.
        """
        client, token, _ = operator

        response = client.put(
            f"/api/v1/admin/users/{account}/roles",
            json={"roles": ["user", "user", "analyst"]},
            headers=auth_headers(token),
        )

        body = response.get_json()
        assert body.get("error") != "EMAIL_ALREADY_REGISTERED", body
        assert response.status_code == 200, body
        assert sorted(body["roles"]) == ["analyst", "user"]
        assert associations(app, account) == 2
