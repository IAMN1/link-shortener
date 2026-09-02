"""``admin:manage_users`` is not permission to reach an account above you.

``require_may_confer`` has always guarded the giving half: nobody hands out
a permission they do not hold. The taking half was unguarded, and deleting,
deactivating and re-roling all take -- so a role carrying
``admin:manage_users`` and nothing else could remove the only ``auditor``,
and with it the only account able to read the audit journal.

That matters because ``admin:all`` deliberately does not carry
``audit:view`` (``BEYOND_ADMIN_ALL``). The separation between administering
the service and reading the record of it was the point, and it was
reachable around the back.

The route decorators are not what is under test here -- ``admin`` is
allowed through them, which is the premise the first test states. What is
under test is what happens one step further in.
"""

import pytest

from tests.integration.conftest import confirm_email, auth_headers


MANAGER_ROLE_ID = "22222222-2222-2222-2222-222222222222"
MANAGER_PERMISSIONS = ["admin:view_users", "admin:manage_users"]

MANAGER_EMAIL = "user-manager@example.com"
MANAGER_PASSWORD = "ManagerPass1!"

AUDITOR_EMAIL = "the-auditor@example.com"
AUDITOR_PASSWORD = "AuditorPass1!"


def _register(client, email, password):
    """
    Register and confirm an account.

    Args:
        client: Test client.
        email: The address to register.
        password: Its password.
    """
    client.post(
        "/api/v1/auth/register", json={"email": email, "password": password}
    )
    confirm_email(client.application, email)


def _user_id(session, email):
    """
    Find a stored account's id.

    Args:
        session: An open database session.
        email: The address to look up.

    Returns:
        The account's id.
    """
    from sqlalchemy import text

    row = session.execute(
        text("SELECT id FROM users WHERE email = :email"), {"email": email}
    ).fetchone()
    assert row is not None, f"{email} was never registered"
    return row[0]


@pytest.fixture
def two_accounts(app, client):
    """
    A manager who may administer users, and an auditor who outranks them.

    The manager's role is built here rather than taken from
    ``roles.yaml``: the shipped set has no such role, which is why the gap
    was not reachable out of the box, and is not a reason it was safe --
    the role editor exists so that operators write roles like this one.

    Args:
        app: The application under test.
        client: A test client for it.

    Returns:
        ``(manager_token, auditor_id)``.
    """
    from sqlalchemy import text

    from link_shortener.infrastructure.database.seed import seed_base_roles

    with app.app_context():
        db = app.container.get_db_manager()
        with db.session() as session:
            seed_base_roles(session)

    _register(client, MANAGER_EMAIL, MANAGER_PASSWORD)
    _register(client, AUDITOR_EMAIL, AUDITOR_PASSWORD)

    with app.app_context():
        db = app.container.get_db_manager()
        with db.session() as session:
            session.execute(text(
                "INSERT OR IGNORE INTO roles (id, name, description, is_system) "
                f"VALUES ('{MANAGER_ROLE_ID}', 'user-manager', "
                "'administers accounts', 0)"
            ))
            for permission in MANAGER_PERMISSIONS:
                row = session.execute(
                    text("SELECT id FROM permissions WHERE name = :name"),
                    {"name": permission},
                ).fetchone()
                assert row is not None, f"{permission} was never seeded"
                session.execute(text(
                    "INSERT OR IGNORE INTO role_permissions "
                    f"(role_id, permission_id) VALUES ('{MANAGER_ROLE_ID}', :pid)"
                ), {"pid": row[0]})

            session.execute(text(
                "INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES "
                f"(:uid, '{MANAGER_ROLE_ID}')"
            ), {"uid": _user_id(session, MANAGER_EMAIL)})

            auditor_role = session.execute(
                text("SELECT id FROM roles WHERE name = 'auditor'")
            ).fetchone()
            assert auditor_role is not None, "the shipped auditor role is gone"
            auditor_id = _user_id(session, AUDITOR_EMAIL)
            session.execute(text(
                "INSERT OR IGNORE INTO user_roles (user_id, role_id) "
                "VALUES (:uid, :rid)"
            ), {"uid": auditor_id, "rid": auditor_role[0]})
            session.commit()

    token = client.post("/api/v1/auth/login", json={
        "email": MANAGER_EMAIL, "password": MANAGER_PASSWORD
    }).get_json()["access_token"]

    return token, auditor_id


class TestThePremise:
    """Without this, the refusals below could mean the wrong thing."""

    def test_the_manager_passes_the_route_decorators(self, client, two_accounts):
        """The role really does hold ``admin:view_users``.

        A 403 further down is then about the account being reached, not
        about the caller being unable to use the admin API at all.
        """
        token, _ = two_accounts

        answer = client.get("/api/v1/admin/users", headers=auth_headers(token))

        assert answer.status_code == 200, answer.get_json()

    def test_the_manager_may_still_administer_an_ordinary_account(
        self, client, two_accounts
    ):
        """The rule must not refuse the work the role exists to do.

        The account is made through the admin API rather than through
        ``/register``: registration is limited to three an hour per
        address, and the fixture has already spent two of them, so a third
        sign-up here would fail for a reason that has nothing to do with
        what is being tested.
        """
        token, _ = two_accounts

        created = client.post(
            "/api/v1/admin/users",
            json={"email": "ordinary@example.com", "password": "OrdinaryPass1!"},
            headers=auth_headers(token),
        )
        assert created.status_code == 201, created.get_json()

        answer = client.post(
            f"/api/v1/admin/users/{created.get_json()['id']}/deactivate",
            headers=auth_headers(token),
        )

        assert answer.status_code == 200, answer.get_json()


class TestTheAuditorIsOutOfReach:
    """Every route that acts on the account, in both directions.

    The rule was written for the three that take authority away, and the
    two that give it back were left out -- so a caller holding
    ``admin:manage_users`` and nothing else could not suspend an
    ``auditor``, could not delete it and could not strip its roles, and
    could switch a suspended one back on or confirm its address, which is
    what decides whether it can sign in at all. Reaching an account whose
    privileges exceed your own is the same reach whichever way the change
    points.
    """

    @pytest.mark.parametrize(
        "method, suffix, body",
        [
            ("DELETE", "", None),
            ("POST", "/deactivate", None),
            ("PUT", "/roles", {"roles": ["user"]}),
            ("POST", "/activate", None),
            ("POST", "/verify-email", None),
            ("POST", "/resend-verification", None),
        ],
    )
    def test_it_is_refused(self, client, two_accounts, method, suffix, body):
        token, auditor_id = two_accounts

        answer = client.open(
            f"/api/v1/admin/users/{auditor_id}{suffix}",
            method=method,
            json=body,
            headers=auth_headers(token),
        )

        assert answer.status_code == 403, (
            f"{method} ...{suffix} answered {answer.status_code}: "
            f"{answer.get_json()}"
        )
        assert answer.get_json()["error"] == "FORBIDDEN"

    def test_the_account_is_still_there_and_still_an_auditor(
        self, app, client, two_accounts
    ):
        """The statuses say refused; this says the database agrees.

        A 403 returned after the work was done would look identical from
        the outside.
        """
        from sqlalchemy import text

        token, auditor_id = two_accounts

        client.delete(
            f"/api/v1/admin/users/{auditor_id}", headers=auth_headers(token)
        )
        client.post(
            f"/api/v1/admin/users/{auditor_id}/deactivate",
            headers=auth_headers(token),
        )
        client.put(
            f"/api/v1/admin/users/{auditor_id}/roles",
            json={"roles": ["user"]},
            headers=auth_headers(token),
        )

        with app.app_context():
            db = app.container.get_db_manager()
            with db.session() as session:
                account = session.execute(
                    text("SELECT is_active FROM users WHERE id = :uid"),
                    {"uid": auditor_id},
                ).fetchone()
                roles = session.execute(text(
                    "SELECT r.name FROM roles r JOIN user_roles ur "
                    "ON ur.role_id = r.id WHERE ur.user_id = :uid"
                ), {"uid": auditor_id}).fetchall()

        assert account is not None, "the auditor was deleted"
        assert account[0], "the auditor was deactivated"
        assert "auditor" in {row[0] for row in roles}, (
            "the auditor lost the role that made it one"
        )
