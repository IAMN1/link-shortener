"""Reading the administration is not permission to change it.

``test_every_admin_route_is_guarded`` asks whether an ordinary user is
refused everywhere, and it is. That leaves the question one step in: a role
built with ``admin:view_users`` and ``admin:view_roles`` and nothing else --
which the admin API itself can create, and the live run does create one --
must still be refused by every route that writes.

Measured with ``ADMIN_MANAGE_USERS`` swapped for ``ADMIN_VIEW_USERS`` on one
decorator: such a role deleted an account, and its links with it, with the
whole suite green. The two constants sit next to each other and read almost
alike, so the swap is a plausible slip rather than an invented one.
"""

import pytest

from tests.integration.conftest import confirm_email, auth_headers


READ_PERMISSIONS = ["admin:view_users", "admin:view_roles"]

VICTIM_ID = "00000000-0000-0000-0000-000000000000"

# Every administrative route that changes something, with a body where one
# is required. The values need not be valid: a caller without the
# permission must be refused before anything is parsed or looked up.
WRITING_ROUTES = [
    ("POST", "/api/v1/admin/users",
     {"email": "made@example.test", "password": "Irrelevant1!"}),
    ("DELETE", f"/api/v1/admin/users/{VICTIM_ID}", None),
    ("PUT", f"/api/v1/admin/users/{VICTIM_ID}/roles", {"roles": ["user"]}),
    ("POST", f"/api/v1/admin/users/{VICTIM_ID}/activate", None),
    ("POST", f"/api/v1/admin/users/{VICTIM_ID}/deactivate", None),
    ("POST", "/api/v1/admin/roles",
     {"name": "made-by-a-reader", "permissions": ["link:create"]}),
    ("DELETE", "/api/v1/admin/roles/user", None),
    ("PUT", "/api/v1/admin/roles/user/permissions",
     {"permissions": ["link:create"]}),
]


@pytest.fixture
def reader_token(app, client):
    """
    Register an account and give it a role that may only read.

    Args:
        app: The application under test.
        client: A test client for it.

    Returns:
        An access token for the read-only account.
    """
    from sqlalchemy import text

    from link_shortener.infrastructure.database.seed import seed_base_roles

    email = "read-only-admin@example.com"
    with app.app_context():
        db = app.container.get_db_manager()
        with db.session() as session:
            seed_base_roles(session)

    client.post("/api/v1/auth/register", json={
        "email": email, "password": "ReaderPass1!"
    })
    confirm_email(client.application, email)

    with app.app_context():
        db = app.container.get_db_manager()
        with db.session() as session:
            session.execute(text(
                "INSERT OR IGNORE INTO roles (id, name, description, is_system) "
                "VALUES ('11111111-1111-1111-1111-111111111111', 'auditor', "
                "'reads the administration', 0)"
            ))
            for permission in READ_PERMISSIONS:
                row = session.execute(
                    text("SELECT id FROM permissions WHERE name = :name"),
                    {"name": permission},
                ).fetchone()
                assert row is not None, f"{permission} was never seeded"
                session.execute(text(
                    "INSERT OR IGNORE INTO role_permissions (role_id, permission_id) "
                    "VALUES ('11111111-1111-1111-1111-111111111111', :pid)"
                ), {"pid": row[0]})
            user = session.execute(
                text("SELECT id FROM users WHERE email = :email"),
                {"email": email},
            ).fetchone()
            session.execute(text(
                "INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES "
                "(:uid, '11111111-1111-1111-1111-111111111111')"
            ), {"uid": user[0]})
            session.commit()

    response = client.post("/api/v1/auth/login", json={
        "email": email, "password": "ReaderPass1!"
    })
    return response.get_json()["access_token"]


class TestARoleThatMayOnlyRead:

    def test_it_can_read(self, client, reader_token):
        # The premise: without this the refusals below could be a token
        # that does not work rather than a permission that is missing.
        for path in ("/api/v1/admin/users", "/api/v1/admin/roles"):
            response = client.get(path, headers=auth_headers(reader_token))
            assert response.status_code == 200, f"{path}: {response.get_json()}"

    @pytest.mark.parametrize("method, path, body", WRITING_ROUTES)
    def test_it_cannot_write(self, client, reader_token, method, path, body):
        response = client.open(
            path, method=method, json=body,
            headers=auth_headers(reader_token),
        )

        assert response.status_code == 403, (
            f"{method} {path} answered {response.status_code} to a role that "
            f"may only read: {response.get_json()}"
        )
        assert response.get_json()["error"] == "FORBIDDEN"

    def test_nothing_it_tried_took_effect(self, app, client, reader_token):
        # The statuses above say the requests were refused; this says the
        # database agrees. A 403 returned after the work was done would
        # look identical up there.
        from sqlalchemy import text

        for method, path, body in WRITING_ROUTES:
            client.open(
                path, method=method, json=body,
                headers=auth_headers(reader_token),
            )

        with app.app_context():
            db = app.container.get_db_manager()
            with db.session() as session:
                made = session.execute(text(
                    "SELECT COUNT(*) FROM users WHERE email = 'made@example.test'"
                )).scalar()
                role = session.execute(text(
                    "SELECT COUNT(*) FROM roles WHERE name = 'made-by-a-reader'"
                )).scalar()
                user_role = session.execute(text(
                    "SELECT COUNT(*) FROM roles WHERE name = 'user'"
                )).scalar()

        assert made == 0, "a read-only role created an account"
        assert role == 0, "a read-only role created a role"
        assert user_role == 1, "a read-only role deleted a system role"
