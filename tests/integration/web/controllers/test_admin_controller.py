"""Integration tests for admin endpoints with real DB."""

import pytest
from tests.integration.conftest import (
    auth_headers, csrf_headers, register_and_login
)


class TestAdminHealthUnauthorized:
    """GET /api/v1/admin/health — requires admin role."""

    def test_unauthorized_returns_401(self, client):
        r = client.get("/api/v1/admin/health")
        assert r.status_code == 401


class TestAdminUsersUnauthorized:
    """GET /api/v1/admin/users — requires admin role."""

    def test_unauthorized_returns_401(self, client):
        r = client.get("/api/v1/admin/users")
        assert r.status_code == 401


class TestAdminRolesUnauthorized:
    """GET /api/v1/admin/roles — requires admin role."""

    def test_unauthorized_returns_401(self, client):
        r = client.get("/api/v1/admin/roles")
        assert r.status_code == 401


class TestAdminWithAdminUser:
    """Tests with an actual admin user."""

    @pytest.fixture(autouse=True)
    def setup_admin(self, app, client):
        """Register user, promote to admin, get token."""
        with app.app_context():
            from link_shortener.infrastructure.database.seed import seed_base_roles
            from link_shortener.infrastructure.database.unit_of_work import SQLAlchemyUnitOfWork
            db = app.container.get_db_manager()
            with db.session() as session:
                seed_base_roles(session)

        # Register
        client.post("/api/v1/auth/register", json={
            "email": "admin@test.com", "password": "AdminPass1!"
        })

        # Promote to admin via DB
        with app.app_context():
            from sqlalchemy import text
            db = app.container.get_db_manager()
            with db.session() as session:
                user = session.execute(
                    text("SELECT id FROM users WHERE email='admin@test.com'")
                ).fetchone()
                admin_role = session.execute(
                    text("SELECT id FROM roles WHERE name='admin'")
                ).fetchone()
                if user and admin_role:
                    session.execute(text(
                        "INSERT OR IGNORE INTO user_roles (user_id, role_id) "
                        "VALUES (:uid, :rid)"
                    ), {"uid": user[0], "rid": admin_role[0]})
                    session.commit()

        # Login
        r = client.post("/api/v1/auth/login", json={
            "email": "admin@test.com", "password": "AdminPass1!"
        })
        self.token = r.get_json().get("access_token")

    def test_admin_health(self, client):
        r = client.get("/api/v1/admin/health", headers=auth_headers(self.token))
        assert r.status_code == 200

    def test_admin_users_list(self, client):
        r = client.get("/api/v1/admin/users", headers=auth_headers(self.token))
        assert r.status_code == 200

    def test_admin_roles_list(self, client):
        r = client.get("/api/v1/admin/roles", headers=auth_headers(self.token))
        assert r.status_code == 200

    def test_a_typo_in_a_permission_does_not_quietly_narrow_a_role(self, client):
        """
        Creating a role with an unknown permission raised; updating one
        with the same typo answered 200 and dropped it. The admin sees a
        success and a role that lost a permission -- and the two endpoints
        disagreed about the same mistake.
        """
        created = client.post(
            "/api/v1/admin/roles",
            json={
                "name": "editor-typo-check",
                "description": "for the typo test",
                "permissions": ["link:create", "link:view_own"],
            },
            headers=csrf_headers(client, auth_headers(self.token)),
        )
        assert created.status_code == 201, created.get_json()

        updated = client.put(
            "/api/v1/admin/roles/editor-typo-check/permissions",
            json={"permissions": ["link:create", "link:vew_own"]},
            headers=csrf_headers(client, auth_headers(self.token)),
        )

        assert updated.status_code == 400, updated.get_json()

        role = client.get(
            "/api/v1/admin/roles/editor-typo-check",
            headers=auth_headers(self.token),
        ).get_json()
        names = {
            item["name"] if isinstance(item, dict) else item
            for item in role["permissions"]
        }
        assert names == {"link:create", "link:view_own"}

    def test_a_correct_update_still_goes_through(self, client):
        client.post(
            "/api/v1/admin/roles",
            json={
                "name": "editor-happy-path",
                "description": "for the typo test",
                "permissions": ["link:create"],
            },
            headers=csrf_headers(client, auth_headers(self.token)),
        )

        updated = client.put(
            "/api/v1/admin/roles/editor-happy-path/permissions",
            json={"permissions": ["link:create", "link:view_own"]},
            headers=csrf_headers(client, auth_headers(self.token)),
        )

        assert updated.status_code == 200, updated.get_json()
