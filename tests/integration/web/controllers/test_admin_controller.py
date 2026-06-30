"""Integration tests for admin endpoints with real DB."""

import pytest
from tests.integration.conftest import register_and_login, auth_headers


class TestAdminHealthUnauthorized:
    """GET /api/v1/admin/health — requires admin role."""

    def test_unauthorized_returns_403(self, client):
        r = client.get("/api/v1/admin/health")
        assert r.status_code in (401, 403)


class TestAdminUsersUnauthorized:
    """GET /api/v1/admin/users — requires admin role."""

    def test_unauthorized_returns_403(self, client):
        r = client.get("/api/v1/admin/users")
        assert r.status_code in (401, 403)


class TestAdminRolesUnauthorized:
    """GET /api/v1/admin/roles — requires admin role."""

    def test_unauthorized_returns_403(self, client):
        r = client.get("/api/v1/admin/roles")
        assert r.status_code in (401, 403)


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
