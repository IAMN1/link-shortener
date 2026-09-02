"""What becomes of an account whose only role is deleted.

Deleting a role takes it off every account at once. An account that wore
nothing else was then left with an empty set — and an empty set is not the
least privilege, it is less than anonymous. Measured on two live walks:
such an account signed in (200) and was refused everything afterwards,
including `POST /api/v1/shorten`, which a caller with no account at all may
do. Nothing said so at deletion time, and nothing distinguished that
account from a working one until it tried something.

The role still goes: what the administrator asked for was that it stop
existing. What changes is where its wearers land — on the role
registration grants, through the same service and the same assignability
policy that door uses.

Driven over HTTP rather than through the use case, because the report that
found this was an HTTP one and the interesting part is what the next
request answers.
"""

import uuid

import pytest

from tests.integration.conftest import (
    account_with_permissions, auth_headers, csrf_headers,
)


@pytest.fixture()
def administrator(app):
    """A client that may manage both users and roles."""
    return account_with_permissions(
        app,
        f"bare-admin-{uuid.uuid4().hex[:8]}@example.com",
        "Str0ng!Passw0rd",
        f"bare-admin-role-{uuid.uuid4().hex[:6]}",
        ["admin:view_users", "admin:manage_users",
         "admin:view_roles", "admin:manage_roles"],
    )


@pytest.fixture()
def subject(app):
    """An ordinary account, and its own client."""
    return account_with_permissions(
        app,
        f"bare-subject-{uuid.uuid4().hex[:8]}@example.com",
        "Str0ng!Passw0rd",
        f"bare-subject-role-{uuid.uuid4().hex[:6]}",
        ["link:create"],
    )


def _roles_of(client, token, user_id):
    """What the admin surface says an account wears."""
    answer = client.get(
        f"/api/v1/admin/users/{user_id}", headers=auth_headers(token)
    )
    assert answer.status_code == 200, answer.get_data(as_text=True)
    # The admin surface answers with role names, not role objects.
    return sorted(answer.get_json()["roles"])


class TestTheOnlyRoleAnAccountWears:

    def _leave_it_wearing_one_role(self, administrator, subject):
        """Give the subject a single role of its own, and return its name."""
        admin_client, admin_token, _ = administrator
        _subject_client, _subject_token, subject_id = subject

        only = f"only-{uuid.uuid4().hex[:8]}"
        created = admin_client.post(
            "/api/v1/admin/roles",
            json={
                "name": only,
                "description": "the account's only role",
                "permissions": ["link:create"],
            },
            headers=csrf_headers(admin_client, auth_headers(admin_token)),
        )
        assert created.status_code == 201, created.get_data(as_text=True)

        given = admin_client.put(
            f"/api/v1/admin/users/{subject_id}/roles",
            json={"roles": [only]},
            headers=csrf_headers(admin_client, auth_headers(admin_token)),
        )
        assert given.status_code == 200, given.get_data(as_text=True)
        assert _roles_of(admin_client, admin_token, subject_id) == [only]
        return only

    def test_deleting_it_leaves_the_account_on_the_default_role(
        self, app, administrator, subject
    ):
        admin_client, admin_token, _ = administrator
        _client, _token, subject_id = subject
        only = self._leave_it_wearing_one_role(administrator, subject)

        deleted = admin_client.delete(
            f"/api/v1/admin/roles/{only}",
            headers=csrf_headers(admin_client, auth_headers(admin_token)),
        )

        assert deleted.status_code == 200, deleted.get_data(as_text=True)
        assert _roles_of(admin_client, admin_token, subject_id) == [
            app.container.config.DEFAULT_ROLE_NAME
        ]

    def test_the_account_can_still_do_what_anyone_can(
        self, administrator, subject
    ):
        """
        The consequence that was measured, stated as itself: the account
        was refused what an anonymous caller may do.
        """
        subject_client, subject_token, _ = subject
        only = self._leave_it_wearing_one_role(administrator, subject)
        admin_client, admin_token, _ = administrator

        admin_client.delete(
            f"/api/v1/admin/roles/{only}",
            headers=csrf_headers(admin_client, auth_headers(admin_token)),
        )

        made = subject_client.post(
            "/api/v1/shorten",
            json={"url": f"https://example.com/{uuid.uuid4().hex}"},
            headers=csrf_headers(subject_client, auth_headers(subject_token)),
        )

        assert made.status_code == 201, made.get_data(as_text=True)

    def test_an_account_wearing_more_than_one_keeps_the_rest(
        self, app, administrator, subject
    ):
        """
        The other half: the fallback is for accounts left bare, not for
        every wearer. An account with a second role keeps that one and
        gains nothing.
        """
        admin_client, admin_token, _ = administrator
        _client, _token, subject_id = subject
        only = self._leave_it_wearing_one_role(administrator, subject)

        spare = f"spare-{uuid.uuid4().hex[:8]}"
        admin_client.post(
            "/api/v1/admin/roles",
            json={
                "name": spare,
                "description": "a second role",
                "permissions": ["link:create"],
            },
            headers=csrf_headers(admin_client, auth_headers(admin_token)),
        )
        admin_client.put(
            f"/api/v1/admin/users/{subject_id}/roles",
            json={"roles": [only, spare]},
            headers=csrf_headers(admin_client, auth_headers(admin_token)),
        )

        admin_client.delete(
            f"/api/v1/admin/roles/{only}",
            headers=csrf_headers(admin_client, auth_headers(admin_token)),
        )

        assert _roles_of(admin_client, admin_token, subject_id) == [spare]

    def test_a_role_nobody_wears_takes_nobody_anywhere(
        self, app, administrator, subject
    ):
        """
        And deleting an unworn role must not hand the default role to
        somebody who never had the deleted one.
        """
        admin_client, admin_token, _ = administrator
        _client, _token, subject_id = subject
        before = _roles_of(admin_client, admin_token, subject_id)

        unworn = f"unworn-{uuid.uuid4().hex[:8]}"
        admin_client.post(
            "/api/v1/admin/roles",
            json={
                "name": unworn,
                "description": "nobody wears this",
                "permissions": ["link:create"],
            },
            headers=csrf_headers(admin_client, auth_headers(admin_token)),
        )

        admin_client.delete(
            f"/api/v1/admin/roles/{unworn}",
            headers=csrf_headers(admin_client, auth_headers(admin_token)),
        )

        assert _roles_of(admin_client, admin_token, subject_id) == before
