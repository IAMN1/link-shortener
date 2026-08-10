"""
The access model of the link API, exercised against a real authorization
service and a real database.

The unit-level controller tests cannot cover any of this: their conftest
replaces the authorization service with a bare ``Mock()``, so every
permission check passes whatever the code asks for. Everything here runs
through the container's real ``RBACAuthorizationService`` and the seeded
``roles`` table.
"""

import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from tests.integration.conftest import confirm_email, auth_headers


# ==============================================================================
# Helpers
# ==============================================================================

def _register_and_login(app, email, password="AccessTest1!"):
    """
    Register a user and return their access token.

    Runs on a throwaway client on purpose. Logging in sets session cookies,
    so registering on the client under test would silently authenticate the
    very requests a test means to send anonymously -- the same mistake that
    made an earlier CSRF test compare two refusals from the wrong layer.
    """
    scratch = app.test_client()
    scratch.post("/api/v1/auth/register", json={"email": email, "password": password})
    confirm_email(scratch.application, email)
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


def _grant_role(app, email, role_name):
    """Attach an existing role to a user."""
    with app.app_context():
        db = app.container.get_db_manager()
        with db.session() as session:
            session.execute(text(
                "INSERT OR IGNORE INTO user_roles (user_id, role_id) "
                "SELECT u.id, r.id FROM users u, roles r "
                "WHERE u.email=:e AND r.name=:r"
            ), {"e": email, "r": role_name})
            session.commit()


def _revoke_role(app, email, role_name):
    """Detach a role from a user."""
    with app.app_context():
        db = app.container.get_db_manager()
        with db.session() as session:
            session.execute(text(
                "DELETE FROM user_roles WHERE user_id IN "
                "(SELECT id FROM users WHERE email=:e) AND role_id IN "
                "(SELECT id FROM roles WHERE name=:r)"
            ), {"e": email, "r": role_name})
            session.commit()


def _set_role_permissions(app, role_name, permission_names):
    """Replace a role's permission set with exactly ``permission_names``."""
    with app.app_context():
        db = app.container.get_db_manager()
        with db.session() as session:
            session.execute(text(
                "DELETE FROM role_permissions WHERE role_id IN "
                "(SELECT id FROM roles WHERE name=:r)"
            ), {"r": role_name})
            for name in permission_names:
                session.execute(text(
                    "INSERT OR IGNORE INTO role_permissions (role_id, permission_id) "
                    "SELECT r.id, p.id FROM roles r, permissions p "
                    "WHERE r.name=:r AND p.name=:p"
                ), {"r": role_name, "p": name})
            session.commit()


def _role_permissions(app, role_name):
    """Read back a role's permission names."""
    with app.app_context():
        db = app.container.get_db_manager()
        with db.session() as session:
            rows = session.execute(text(
                "SELECT p.name FROM permissions p "
                "JOIN role_permissions rp ON rp.permission_id = p.id "
                "JOIN roles r ON r.id = rp.role_id WHERE r.name=:r"
            ), {"r": role_name}).fetchall()
    return [row[0] for row in rows]


def _insert_link(app, code, owner_id=None, expires_at=None, url=None, clicks=0):
    """
    Insert a link row directly, bypassing the creation path.

    ``REPLACE`` rather than ``INSERT``: the app fixture is session-scoped,
    so a per-test setup runs against a database earlier tests have already
    written to -- and deleted from.
    """
    with app.app_context():
        db = app.container.get_db_manager()
        with db.session() as session:
            session.execute(text(
                "INSERT OR REPLACE INTO urls (id, url_hash, short_code, original_url, "
                "created_at, clicks, expires_at, owner_id) "
                "VALUES (:id, :hash, :code, :url, :created, :clicks, "
                ":expires, :owner)"
            ), {
                "id": f"row-{code}",
                # A real hex digest: the repository rebuilds a UrlHash from
                # this column, and anything else fails on the way out.
                "hash": hashlib.sha256(code.encode()).hexdigest(),
                "code": code,
                "url": url or f"https://example.com/{code}",
                "created": datetime.now(timezone.utc) - timedelta(days=1),
                "clicks": clicks,
                "expires": expires_at,
                "owner": owner_id,
            })
            session.commit()


def _delete_role(app, role_name):
    """Remove a role row entirely, as an unseeded database would have it."""
    with app.app_context():
        db = app.container.get_db_manager()
        with db.session() as session:
            session.execute(text(
                "DELETE FROM role_permissions WHERE role_id IN "
                "(SELECT id FROM roles WHERE name=:r)"
            ), {"r": role_name})
            session.execute(
                text("DELETE FROM roles WHERE name=:r"), {"r": role_name}
            )
            session.commit()


@pytest.fixture()
def restore_guest_role(app):
    """
    Put the ``guest`` role back the way the seed left it.

    Restores the row as well as its permissions: one of these tests deletes
    the role outright, and the session-scoped database is shared with every
    test that follows.
    """
    original = _role_permissions(app, "guest")
    yield
    with app.app_context():
        from link_shortener.infrastructure.database.seed import seed_base_roles
        db = app.container.get_db_manager()
        with db.session() as session:
            seed_base_roles(session)
    _set_role_permissions(app, "guest", original)


# ==============================================================================
# The guest role, and the ceiling above it
# ==============================================================================

class TestAnonymousActsAsGuest:
    """An unauthenticated caller is answered from the stored guest role."""

    def test_anonymous_can_still_shorten(self, client):
        r = client.post("/api/v1/shorten", json={"url": "https://guest-ok.example"})
        assert r.status_code == 201

    def test_revoking_link_create_from_guest_stops_anonymous_shortening(
        self, app, client, restore_guest_role
    ):
        """The check is live, not decorative: take the grant away and it bites."""
        _set_role_permissions(app, "guest", ["stats:view_basic"])

        r = client.post("/api/v1/shorten", json={"url": "https://guest-denied.example"})

        assert r.status_code == 401

    def test_guest_role_cannot_be_widened_past_the_ceiling(
        self, app, client, restore_guest_role
    ):
        """
        Granting an admin permission to ``guest`` must not hand it to the
        internet. This is the failure Kubernetes shipped and GKE 1.28 later
        refused in code.

        The permission granted is exactly the one the endpoint asks for.
        Granting ``admin:all`` instead would prove nothing: the super-user
        bypass is not reachable anonymously, so such a test passes with the
        ceiling removed -- which is how this test was written first.
        """
        _set_role_permissions(
            app, "guest", ["stats:view_basic", "link:create", "admin:view_users"]
        )

        assert client.get("/api/v1/admin/users").status_code == 401

    def test_admin_all_in_the_guest_role_grants_no_bypass(
        self, app, client, restore_guest_role
    ):
        """The super-user shortcut is for authenticated callers only."""
        _set_role_permissions(app, "guest", ["admin:all"])

        assert client.get("/api/v1/admin/users").status_code == 401
        assert client.get("/api/v1/admin/roles").status_code == 401

    def test_logged_in_user_without_link_create_gets_403_not_401(
        self, app, client
    ):
        """
        The other half of the 401/403 split. The analyst role deliberately
        has no ``link:create``, and this caller is logged in -- logging in
        again is not what they are missing.
        """
        email = "analyst-create@test.com"
        token = _register_and_login(app, email)
        _revoke_role(app, email, "user")
        _grant_role(app, email, "analyst")

        r = client.post(
            "/api/v1/shorten",
            json={"url": "https://analyst-create.example"},
            headers=auth_headers(token),
        )

        assert r.status_code == 403

    def test_absent_guest_role_denies_rather_than_defaults(
        self, app, client, restore_guest_role
    ):
        """
        A database with no ``guest`` row has not said what a guest may do.
        Answering from the ceiling instead would turn a maximum into a
        default and make a half-seeded deployment look like a configured
        one.

        The role is deleted, not emptied: an empty role exercises a
        different branch, and a test that empties it stays green with the
        fail-closed branch inverted.
        """
        _delete_role(app, "guest")

        r = client.post("/api/v1/shorten", json={"url": "https://no-guest.example"})

        assert r.status_code == 401

    def test_guest_role_stripped_of_link_create_denies_creation(
        self, app, client, restore_guest_role
    ):
        """The role exists and simply does not grant it."""
        _set_role_permissions(app, "guest", [])

        r = client.post("/api/v1/shorten", json={"url": "https://empty-guest.example"})

        assert r.status_code == 401


# ==============================================================================
# What a public read may disclose
# ==============================================================================

class TestOwnerIdDisclosure:
    """The owner's identifier is not part of the public answer."""

    @pytest.fixture(autouse=True)
    def setup(self, app, client):
        self.owner_email = "owner-disclose@test.com"
        self.token = _register_and_login(app, self.owner_email)
        self.owner = _user_id(app, self.owner_email)
        _insert_link(app, "OWNED1", owner_id=self.owner, clicks=42)

    def test_anonymous_does_not_see_the_counters(self, client):
        """
        They go out with the identifier. Every field ``/extended``
        withholds is arithmetic on these two, so leaving them public made
        that endpoint's restriction a formality.
        """
        body = client.get("/api/v1/links/OWNED1").get_json()

        assert body["clicks"] is None
        assert body["last_accessed"] is None
        # What a public caller still gets: where the code points, and when.
        assert body["original_url"]
        assert body["created_at"]

    def test_owner_sees_the_counters(self, client):
        body = client.get(
            "/api/v1/links/OWNED1", headers=auth_headers(self.token)
        ).get_json()

        assert body["clicks"] == 42

    def test_another_user_does_not_see_the_counters(self, app, client):
        other = _register_and_login(app, "other-counters@test.com")

        body = client.get(
            "/api/v1/links/OWNED1", headers=auth_headers(other)
        ).get_json()

        assert body["clicks"] is None

    def test_analyst_sees_the_counters(self, app, client):
        analyst_email = "analyst-counters@test.com"
        analyst = _register_and_login(app, analyst_email)
        _grant_role(app, analyst_email, "analyst")

        body = client.get(
            "/api/v1/links/OWNED1", headers=auth_headers(analyst)
        ).get_json()

        assert body["clicks"] == 42

    def test_anonymous_does_not_see_owner_id(self, client):
        r = client.get("/api/v1/links/OWNED1")

        assert r.status_code == 200
        assert r.get_json()["owner_id"] is None

    def test_owner_sees_own_owner_id(self, client):
        r = client.get("/api/v1/links/OWNED1", headers=auth_headers(self.token))

        assert r.status_code == 200
        assert r.get_json()["owner_id"] == self.owner

    def test_another_user_does_not_see_owner_id(self, app, client):
        other = _register_and_login(app, "other-disclose@test.com")

        r = client.get("/api/v1/links/OWNED1", headers=auth_headers(other))

        assert r.status_code == 200
        assert r.get_json()["owner_id"] is None


class TestExtendedInfoIsPrivate:
    """Traffic analytics belong to whoever owns the link."""

    @pytest.fixture(autouse=True)
    def setup(self, app, client):
        self.owner_email = "owner-ext@test.com"
        self.token = _register_and_login(app, self.owner_email)
        self.owner = _user_id(app, self.owner_email)
        _insert_link(app, "EXTND1", owner_id=self.owner, clicks=7)

    def test_anonymous_is_refused_with_401(self, client):
        assert client.get("/api/v1/links/EXTND1/extended").status_code == 401

    def test_unrelated_user_is_refused_with_403(self, app, client):
        other = _register_and_login(app, "other-ext@test.com")

        r = client.get(
            "/api/v1/links/EXTND1/extended", headers=auth_headers(other)
        )

        # 403, not 401: this caller is logged in, and logging in again is
        # not the missing piece.
        assert r.status_code == 403

    def test_owner_is_allowed(self, client):
        r = client.get(
            "/api/v1/links/EXTND1/extended", headers=auth_headers(self.token)
        )

        assert r.status_code == 200
        assert r.get_json()["clicks"] == 7

    def test_analyst_may_read_a_link_they_do_not_own(self, app, client):
        """``stats:view_any`` is what the analyst role exists for."""
        analyst_email = "analyst-ext@test.com"
        analyst = _register_and_login(app, analyst_email)
        _grant_role(app, analyst_email, "analyst")

        r = client.get(
            "/api/v1/links/EXTND1/extended", headers=auth_headers(analyst)
        )

        assert r.status_code == 200

    def test_guest_owned_link_is_not_everyones(self, app, client):
        """A link with no owner is nobody's, not everybody's."""
        _insert_link(app, "NOOWNR", owner_id=None)
        someone = _register_and_login(app, "someone-ext@test.com")

        r = client.get(
            "/api/v1/links/NOOWNR/extended", headers=auth_headers(someone)
        )

        assert r.status_code == 403


# ==============================================================================
# Expiry
# ==============================================================================

class TestExpiredLinkAnswersLikeTheRedirect:
    """410 on both paths, so the two cannot disagree about one code."""

    @pytest.fixture(autouse=True)
    def setup(self, app, client):
        self.email = "expiry-owner@test.com"
        self.token = _register_and_login(app, self.email)
        self.owner = _user_id(app, self.email)
        _insert_link(
            app,
            "EXPRD1",
            owner_id=self.owner,
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )

    def test_basic_info_reports_410(self, client):
        assert client.get("/api/v1/links/EXPRD1").status_code == 410

    def test_extended_info_reports_410(self, client):
        r = client.get(
            "/api/v1/links/EXPRD1/extended", headers=auth_headers(self.token)
        )
        assert r.status_code == 410

    def test_redirect_agrees(self, client):
        assert client.get("/EXPRD1", follow_redirects=False).status_code == 410

    def test_owner_can_still_delete_an_expired_link(self, client):
        """
        Expiry decides what may be served, not who owns what. Routing the
        deletion check through the info endpoint would have made an expired
        link undeletable by the person holding it.
        """
        r = client.delete(
            "/api/v1/links/EXPRD1", headers=auth_headers(self.token)
        )

        assert r.status_code == 200


# ==============================================================================
# Deletion
# ==============================================================================

class TestDeletionOwnership:
    """Who may delete is decided from the stored row."""

    @pytest.fixture(autouse=True)
    def setup(self, app, client):
        self.owner_email = "owner-del@test.com"
        self.token = _register_and_login(app, self.owner_email)
        self.owner = _user_id(app, self.owner_email)

    def test_owner_may_delete_their_own(self, app, client):
        _insert_link(app, "MYDEL1", owner_id=self.owner)

        r = client.delete("/api/v1/links/MYDEL1", headers=auth_headers(self.token))

        assert r.status_code == 200

    def test_a_stranger_may_not(self, app, client):
        _insert_link(app, "NOTYRS", owner_id=self.owner)
        other = _register_and_login(app, "stranger-del@test.com")

        r = client.delete("/api/v1/links/NOTYRS", headers=auth_headers(other))

        assert r.status_code == 403
        # And the row survived the attempt.
        assert client.get("/api/v1/links/NOTYRS").status_code == 200

    def test_a_stranger_may_not_delete_a_guest_link_either(self, app, client):
        _insert_link(app, "GSTDEL", owner_id=None)
        other = _register_and_login(app, "stranger-guest-del@test.com")

        r = client.delete("/api/v1/links/GSTDEL", headers=auth_headers(other))

        assert r.status_code == 403

    def test_the_cli_deletes_without_asking(self, app):
        """
        Pins a decision rather than a mechanism.

        ``flask link delete`` passes ``enforce_ownership=False``: the
        operator already has the database and the configuration, so a check
        here would guard nothing that ``psql`` does not open. Nothing else
        recorded that, so flipping the flag would have gone unnoticed.
        """
        _insert_link(app, "CLIDEL", owner_id=self.owner)

        result = app.test_cli_runner().invoke(args=["link", "delete", "CLIDEL"])

        assert result.exit_code == 0
        with app.app_context():
            db = app.container.get_db_manager()
            with db.session() as session:
                row = session.execute(
                    text("SELECT id FROM urls WHERE short_code='CLIDEL'")
                ).fetchone()
        assert row is None

    def test_admin_may_delete_anyones(self, app, client):
        _insert_link(app, "ADMDEL", owner_id=self.owner)
        admin_email = "admin-del@test.com"
        admin = _register_and_login(app, admin_email)
        _grant_role(app, admin_email, "admin")

        r = client.delete("/api/v1/links/ADMDEL", headers=auth_headers(admin))

        assert r.status_code == 200

    def test_a_user_without_delete_any_is_refused(self, app, client):
        """
        The ``delete_any`` branch: the caller owns nothing here.
        """
        _insert_link(app, "ANLDEL", owner_id=None)
        analyst_email = "analyst-del@test.com"
        analyst = _register_and_login(app, analyst_email)
        _revoke_role(app, analyst_email, "user")
        _grant_role(app, analyst_email, "analyst")

        r = client.delete("/api/v1/links/ANLDEL", headers=auth_headers(analyst))

        assert r.status_code == 403

    def test_the_owner_still_needs_delete_own(self, app, client):
        """
        The ``delete_own`` branch, which the test above does not reach.

        Owning the link is not by itself permission to delete it. The
        analyst role is deliberately without ``link:delete_own``, so a link
        that genuinely belongs to this caller is still refused -- and the
        refusal comes from the permission, not from the ownership check.
        """
        owner_email = "analyst-owner-del@test.com"
        token = _register_and_login(app, owner_email)
        owner = _user_id(app, owner_email)
        _insert_link(app, "OWNANL", owner_id=owner)
        _revoke_role(app, owner_email, "user")
        _grant_role(app, owner_email, "analyst")

        r = client.delete("/api/v1/links/OWNANL", headers=auth_headers(token))

        assert r.status_code == 403
        assert client.get("/api/v1/links/OWNANL").status_code == 200


# ==============================================================================
# Service statistics
# ==============================================================================

class TestPopularLinksNeedViewFull:
    """Totals and other people's URLs are different disclosures."""

    @pytest.fixture(autouse=True)
    def setup(self, app, client):
        _insert_link(app, "POPUL1", owner_id=None, clicks=99)

    def test_anonymous_gets_totals_only(self, client):
        """
        The guest role carries ``stats:view_basic``, so totals are public
        now that the role is actually consulted. They were 403 before, when
        the role existed only in the database.
        """
        r = client.get("/api/v1/stats")

        assert r.status_code == 200
        assert r.get_json()["popular_links"] == []

    def test_plain_user_gets_totals_without_the_breakdown(self, app, client):
        token = _register_and_login(app, "plain-stats@test.com")

        r = client.get("/api/v1/stats", headers=auth_headers(token))

        assert r.status_code == 200
        body = r.get_json()
        assert "total_urls" in body
        assert body["popular_links"] == []

    def test_analyst_gets_the_breakdown(self, app, client):
        analyst_email = "analyst-stats@test.com"
        token = _register_and_login(app, analyst_email)
        _grant_role(app, analyst_email, "analyst")

        r = client.get("/api/v1/stats", headers=auth_headers(token))

        assert r.status_code == 200
        assert r.get_json()["popular_links"] != []
