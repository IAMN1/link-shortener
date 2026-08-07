"""
Nobody hands out what they do not hold, and the last administrator stays.

Both rules were absent, and both gaps were one request wide: a role
carrying ``admin:manage_users`` could assign itself the ``admin`` role, and
a role carrying ``admin:manage_roles`` could write ``admin:all`` into
itself. Either way the "moderator" read back full administrative access.

Everything here runs against the real container: the real authorization
service, the real roles table, real transactions. The unit-level admin
tests cannot cover it -- their conftest replaces the authorization service
with a bare ``Mock()``, so every one of them passes with the decorators
removed entirely.
"""

import uuid

import pytest
from sqlalchemy import text

from tests.integration.conftest import auth_headers


# ==============================================================================
# Helpers
# ==============================================================================

def _register_and_login(app, email, password="Escalate1!"):
    """Register on a throwaway client and return the access token."""
    scratch = app.test_client()
    scratch.post("/api/v1/auth/register", json={"email": email, "password": password})
    r = scratch.post("/api/v1/auth/login", json={"email": email, "password": password})
    return r.get_json().get("access_token")


def _user_id(app, email):
    """Look up a user's id by email."""
    with app.app_context():
        db = app.container.get_db_manager()
        with db.session() as session:
            row = session.execute(
                text("SELECT id FROM users WHERE email=:e"), {"e": email}
            ).fetchone()
    return row[0] if row else None


def _make_role(app, name, permission_names, is_system=False):
    """Create a role directly, with exactly these permissions."""
    with app.app_context():
        db = app.container.get_db_manager()
        with db.session() as session:
            session.execute(
                text("DELETE FROM role_permissions WHERE role_id IN "
                     "(SELECT id FROM roles WHERE name=:r)"), {"r": name}
            )
            session.execute(text("DELETE FROM roles WHERE name=:r"), {"r": name})
            session.execute(text(
                "INSERT INTO roles (id, name, description, is_system) "
                "VALUES (:id, :name, :descr, :sys)"
            ), {
                "id": str(uuid.uuid4()),
                "name": name,
                "descr": f"test role {name}",
                "sys": is_system,
            })
            for permission in permission_names:
                session.execute(text(
                    "INSERT INTO role_permissions (role_id, permission_id) "
                    "SELECT r.id, p.id FROM roles r, permissions p "
                    "WHERE r.name=:r AND p.name=:p"
                ), {"r": name, "p": permission})
            session.commit()


def _set_roles(app, email, role_names):
    """Give a user exactly these roles."""
    with app.app_context():
        db = app.container.get_db_manager()
        with db.session() as session:
            session.execute(text(
                "DELETE FROM user_roles WHERE user_id IN "
                "(SELECT id FROM users WHERE email=:e)"
            ), {"e": email})
            for role in role_names:
                session.execute(text(
                    "INSERT INTO user_roles (user_id, role_id) "
                    "SELECT u.id, r.id FROM users u, roles r "
                    "WHERE u.email=:e AND r.name=:r"
                ), {"e": email, "r": role})
            session.commit()


def _permissions_of(app, email):
    """Read back every permission a user actually holds."""
    with app.app_context():
        db = app.container.get_db_manager()
        with db.session() as session:
            rows = session.execute(text(
                "SELECT DISTINCT p.name FROM permissions p "
                "JOIN role_permissions rp ON rp.permission_id = p.id "
                "JOIN user_roles ur ON ur.role_id = rp.role_id "
                "JOIN users u ON u.id = ur.user_id WHERE u.email=:e"
            ), {"e": email}).fetchall()
    return {row[0] for row in rows}


def _drop_user(app, email):
    """Remove a user so a later test starts from a known count."""
    with app.app_context():
        db = app.container.get_db_manager()
        with db.session() as session:
            session.execute(text(
                "DELETE FROM user_roles WHERE user_id IN "
                "(SELECT id FROM users WHERE email=:e)"
            ), {"e": email})
            session.execute(text("DELETE FROM users WHERE email=:e"), {"e": email})
            session.commit()


# ==============================================================================
# Granting roles
# ==============================================================================

class TestAModeratorCannotBecomeAnAdministrator:
    """``admin:manage_users`` is not a longer spelling of ``admin:all``."""

    @pytest.fixture(autouse=True)
    def setup(self, app):
        self.email = "usermod@test.com"
        self.token = _register_and_login(app, self.email)
        _make_role(
            app, "usermod",
            ["admin:manage_users", "admin:view_users", "link:create"],
        )
        _set_roles(app, self.email, ["usermod"])
        self.uid = _user_id(app, self.email)

    def test_cannot_assign_itself_the_admin_role(self, app, client):
        r = client.put(
            f"/api/v1/admin/users/{self.uid}/roles",
            json={"roles": ["admin"]},
            headers=auth_headers(self.token),
        )

        assert r.status_code == 403
        # And the refusal was real, not merely reported.
        assert "admin:all" not in _permissions_of(app, self.email)

    def test_cannot_assign_the_admin_role_to_somebody_else(self, app, client):
        victim_email = "usermod-target@test.com"
        _register_and_login(app, victim_email)
        victim = _user_id(app, victim_email)

        r = client.put(
            f"/api/v1/admin/users/{victim}/roles",
            json={"roles": ["admin"]},
            headers=auth_headers(self.token),
        )

        assert r.status_code == 403
        assert "admin:all" not in _permissions_of(app, victim_email)

    def test_cannot_create_a_new_administrator(self, client):
        r = client.post(
            "/api/v1/admin/users",
            json={
                "email": "minted-admin@test.com",
                "password": "Escalate1!",
                "roles": ["admin"],
            },
            headers=auth_headers(self.token),
        )

        assert r.status_code == 403

    def test_may_still_grant_what_it_holds(self, app, client):
        """The rule constrains, it does not disable the role."""
        _make_role(app, "usermod_grantable", ["link:create"])
        target_email = "usermod-ok@test.com"
        _register_and_login(app, target_email)
        target = _user_id(app, target_email)

        r = client.put(
            f"/api/v1/admin/users/{target}/roles",
            json={"roles": ["usermod_grantable"]},
            headers=auth_headers(self.token),
        )

        assert r.status_code == 200
        assert _permissions_of(app, target_email) == {"link:create"}


class TestARoleEditorCannotWidenItsOwnRole:
    """``admin:manage_roles`` is not a two-step spelling of ``admin:all``."""

    @pytest.fixture(autouse=True)
    def setup(self, app):
        self.email = "rolemod@test.com"
        self.token = _register_and_login(app, self.email)
        _make_role(app, "rolemod", ["admin:manage_roles", "link:create"])
        _set_roles(app, self.email, ["rolemod"])

    def test_cannot_write_admin_all_into_its_own_role(self, app, client):
        r = client.put(
            "/api/v1/admin/roles/rolemod/permissions",
            json={"permissions": ["admin:all"]},
            headers=auth_headers(self.token),
        )

        assert r.status_code == 403
        assert "admin:all" not in _permissions_of(app, self.email)

    def test_cannot_create_a_role_carrying_more_than_it_holds(self, client):
        r = client.post(
            "/api/v1/admin/roles",
            json={
                "name": "smuggled",
                "description": "…",
                "permissions": ["admin:all"],
            },
            headers=auth_headers(self.token),
        )

        assert r.status_code == 403

    def test_may_still_create_a_role_within_its_own_permissions(self, client):
        r = client.post(
            "/api/v1/admin/roles",
            json={
                "name": "rolemod_child",
                "description": "…",
                "permissions": ["link:create"],
            },
            headers=auth_headers(self.token),
        )

        assert r.status_code == 201


class TestAnAdministratorIsStillUnrestricted:
    """The rule must not have disarmed the role it is meant to protect."""

    @pytest.fixture(autouse=True)
    def setup(self, app):
        self.email = "real-admin@test.com"
        self.token = _register_and_login(app, self.email)
        _set_roles(app, self.email, ["admin"])

    def test_admin_may_grant_the_admin_role(self, app, client):
        target_email = "promoted@test.com"
        _register_and_login(app, target_email)
        target = _user_id(app, target_email)

        r = client.put(
            f"/api/v1/admin/users/{target}/roles",
            json={"roles": ["admin"]},
            headers=auth_headers(self.token),
        )

        assert r.status_code == 200
        assert "admin:all" in _permissions_of(app, target_email)

    def test_admin_may_create_a_role_with_any_permission(self, client):
        r = client.post(
            "/api/v1/admin/roles",
            json={
                "name": "admin_made",
                "description": "…",
                "permissions": ["admin:all", "link:create"],
            },
            headers=auth_headers(self.token),
        )

        assert r.status_code == 201


# ==============================================================================
# The last administrator
# ==============================================================================

class TestTheLastAdministratorStays:
    """
    Losing the final holder of ``admin:all`` leaves a system whose admin
    surface can only be recovered from a shell.
    """

    @pytest.fixture(autouse=True)
    def setup(self, app):
        # Every other admin this module created is cleared away, so "last"
        # means last.
        for stale in (
            "real-admin@test.com", "promoted@test.com", "admin@test.com",
        ):
            _drop_user(app, stale)
        self.email = "sole-admin@test.com"
        self.token = _register_and_login(app, self.email)
        _set_roles(app, self.email, ["admin"])
        self.uid = _user_id(app, self.email)

    def test_cannot_be_deleted(self, app, client):
        r = client.delete(
            f"/api/v1/admin/users/{self.uid}", headers=auth_headers(self.token)
        )

        assert r.status_code == 403
        assert _user_id(app, self.email) is not None

    def test_cannot_be_deactivated(self, client):
        r = client.post(
            f"/api/v1/admin/users/{self.uid}/deactivate",
            headers=auth_headers(self.token),
        )

        assert r.status_code == 403

    def test_cannot_demote_itself(self, app, client):
        r = client.put(
            f"/api/v1/admin/users/{self.uid}/roles",
            json={"roles": ["user"]},
            headers=auth_headers(self.token),
        )

        assert r.status_code == 403
        assert "admin:all" in _permissions_of(app, self.email)

    def test_may_be_demoted_once_another_administrator_exists(self, app, client):
        """The guard is about the last one, not about administrators."""
        spare_email = "spare-admin@test.com"
        _register_and_login(app, spare_email)
        _set_roles(app, spare_email, ["admin"])

        r = client.put(
            f"/api/v1/admin/users/{self.uid}/roles",
            json={"roles": ["user"]},
            headers=auth_headers(self.token),
        )

        assert r.status_code == 200
        assert "admin:all" not in _permissions_of(app, self.email)
