"""
Tests the two answers a taken name gets, which must not be the same answer.

Creating a role under a name somebody holds answers `409
ROLE_ALREADY_EXISTS`. Creating an account under an address somebody holds
answered `400 VALIDATION_ERROR` -- the generic code every malformed field
carries -- so a client telling "that address is taken" from "that address
is not an address" had to read the sentence, which changes with the
reader's language. One situation, two statuses and two codes, on
neighbouring routes of one controller.

The second half of this file is the reason the fix is a `ValidationError`
subclass rather than a class of its own. Public registration does not
refuse a taken address out loud: it answers 202 and mails the address a
notice, which is what OWASP's Authentication Cheat Sheet asks for under
*Account creation*. It recognises the clash by catching `ValidationError`
and reading `field == "email"`. An error that stopped being one would
leave that catch unmatched and the endpoint would answer 500 where it
answers 202 -- and the difference between 202 and 500 is exactly the
disclosure the 202 exists to prevent.
"""

import pytest

from tests.integration.conftest import account_with_permissions, auth_headers


PASSWORD = "TakenPass1!"
TAKEN = "already-here@example.test"


@pytest.fixture(scope="module")
def operator(app):
    """An account that may create users and roles."""
    return account_with_permissions(
        app,
        "creates-things@example.test",
        PASSWORD,
        "creates-things",
        ["admin:manage_users", "admin:manage_roles", "admin:view_users"],
    )


@pytest.fixture(scope="module")
def taken_address(operator):
    """An address the service already has an account under."""
    client, token, _ = operator
    made = client.post(
        "/api/v1/admin/users",
        json={"email": TAKEN, "password": PASSWORD},
        headers=auth_headers(token),
    )
    assert made.status_code == 201, made.get_json()
    return TAKEN


class TestTheAdministrativeRoutesAgree:

    def test_a_taken_address_is_a_conflict(self, operator, taken_address):
        client, token, _ = operator

        response = client.post(
            "/api/v1/admin/users",
            json={"email": taken_address, "password": PASSWORD},
            headers=auth_headers(token),
        )

        assert response.status_code == 409, response.get_json()
        assert response.get_json()["error"] == "EMAIL_ALREADY_REGISTERED"

    def test_a_taken_role_name_is_the_same_kind_of_conflict(self, operator):
        """The route this one was brought into line with."""
        client, token, _ = operator
        body = {
            "name": "already-a-role",
            "description": "taken",
            "permissions": ["link:create"],
        }
        first = client.post(
            "/api/v1/admin/roles", json=body, headers=auth_headers(token)
        )
        assert first.status_code == 201, first.get_json()

        response = client.post(
            "/api/v1/admin/roles", json=body, headers=auth_headers(token)
        )

        assert response.status_code == 409, response.get_json()
        assert response.get_json()["error"] == "ROLE_ALREADY_EXISTS"

    def test_a_malformed_address_is_still_a_validation_error(self, operator):
        """
        The distinction the shared code destroyed: a taken address and a
        malformed one are different answers, and both used to be 400
        ``VALIDATION_ERROR``.
        """
        client, token, _ = operator

        response = client.post(
            "/api/v1/admin/users",
            json={"email": "not-an-address", "password": PASSWORD},
            headers=auth_headers(token),
        )

        assert response.status_code == 400
        assert response.get_json()["error"] != "EMAIL_ALREADY_REGISTERED"


class TestPublicRegistrationStaysSilent:
    """
    The half that must not change. Registration answers a taken address
    exactly as it answers a free one, and the account is not created
    twice.
    """

    def test_registering_a_taken_address_answers_like_a_free_one(
        self, app, taken_address
    ):
        free = app.test_client().post(
            "/api/v1/auth/register",
            json={"email": "never-seen@example.test", "password": PASSWORD},
        )
        taken = app.test_client().post(
            "/api/v1/auth/register",
            json={"email": taken_address, "password": PASSWORD},
        )

        assert taken.status_code == free.status_code == 202
        assert taken.get_json() == free.get_json(), (
            "the two answers differ, which says whether the address is taken"
        )

    def test_the_taken_address_still_has_one_account(
        self, app, taken_address
    ):
        from sqlalchemy import text

        with app.app_context():
            with app.container.get_db_manager().session() as session:
                count = session.execute(
                    text("SELECT COUNT(*) FROM users WHERE email = :e"),
                    {"e": taken_address},
                ).scalar()

        assert count == 1
