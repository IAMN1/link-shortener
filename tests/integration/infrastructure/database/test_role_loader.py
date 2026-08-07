"""Integration tests for RBAC seeding against a real database."""

import pytest

from link_shortener.infrastructure.configs.app.testing import TestingConfig
from link_shortener.infrastructure.database.models.permission_model import (
    PermissionModel
)
from link_shortener.infrastructure.database.models.role_model import RoleModel
from link_shortener.infrastructure.database.role_loader import RoleLoader
from link_shortener.infrastructure.database.seed import (
    DEFAULT_RBAC_CONFIG_PATH, seed_base_roles
)
from link_shortener.web.app_factory import create_app


@pytest.fixture()
def fresh_db(tmp_path):
    """
    A database with tables but nothing seeded.

    The shared ``app`` fixture is session-scoped and already seeded, which
    hides first-pass seeding bugs -- these tests need a genuinely empty one.
    """
    class FreshConfig(TestingConfig):
        TESTING = True
        SECRET_KEY = "role-loader-test-secret"
        SHORT_CODE_SECRET_PEPPER = "role-loader-test-pepper"
        DATABASE_URL = f"sqlite:///{tmp_path}/fresh.db"
        REDIS_ENABLED = False
        CACHE_ENABLED = False
        LOGGING_ENABLED = False
        AUDIT_ENABLED = False
        AUTO_SEED_ROLES = False
        BASE_URL = "http://testserver/"
        HOST = "testserver"
        PORT = 80

    application = create_app(config=FreshConfig())
    with application.app_context():
        db_manager = application.container.get_db_manager()
        db_manager.create_tables()
        yield db_manager
        application.container.close()


def _role_permission_counts(db_manager):
    """
    Count the permissions attached to every seeded role.

    Args:
        db_manager: Database manager for the seeded database.

    Returns:
        Dict of role name to number of permissions.
    """
    with db_manager.session() as session:
        return {
            role.name: len(role.permissions)
            for role in session.query(RoleModel).all()
        }


class TestBaseRoleSeeding:
    """Seeding has to work on the first pass, not the second."""

    def test_single_pass_grants_permissions(self, fresh_db):
        with fresh_db.session() as session:
            seed_base_roles(session)

        counts = _role_permission_counts(fresh_db)
        assert counts, "no roles were created at all"
        # Permissions are queried right after being added in the same
        # session; without a flush they are invisible and every role lands
        # with an empty set, leaving a fresh deployment with no working admin.
        assert counts.get("admin", 0) > 0, (
            f"admin has no permissions after one seeding pass: {counts}"
        )

    def test_seeding_is_idempotent(self, fresh_db):
        with fresh_db.session() as session:
            seed_base_roles(session)
        first = _role_permission_counts(fresh_db)

        with fresh_db.session() as session:
            seed_base_roles(session)
        second = _role_permission_counts(fresh_db)

        assert first == second


class TestAnOperatorsEditSurvivesSeeding:
    """
    Seeding with ``update_existing=False`` promises not to touch what is
    already there -- and did touch it.

    ``_upsert_role`` reassigned ``role.permissions`` unconditionally, so a
    permission granted to a system role through the admin API was taken back
    at the next pass. In ``development``, where ``AUTO_SEED_ROLES`` is on,
    that is every application start: the change looked applied, answered 200,
    and was gone by the next restart.
    """

    def test_a_granted_permission_is_still_there_after_seeding(self, fresh_db):
        with fresh_db.session() as session:
            seed_base_roles(session)

        with fresh_db.session() as session:
            guest = session.query(RoleModel).filter_by(name="guest").one()
            extra = (
                session.query(PermissionModel)
                .filter(~PermissionModel.roles.any(RoleModel.name == "guest"))
                .first()
            )
            granted = extra.name
            guest.permissions.append(extra)

        with fresh_db.session() as session:
            seed_base_roles(session)

        with fresh_db.session() as session:
            guest = session.query(RoleModel).filter_by(name="guest").one()
            assert granted in {p.name for p in guest.permissions}

    def test_a_revoked_permission_stays_revoked(self, fresh_db):
        """The other direction: seeding does not hand it back either."""
        with fresh_db.session() as session:
            seed_base_roles(session)

        with fresh_db.session() as session:
            guest = session.query(RoleModel).filter_by(name="guest").one()
            removed = guest.permissions[0].name
            guest.permissions = guest.permissions[1:]

        with fresh_db.session() as session:
            seed_base_roles(session)

        with fresh_db.session() as session:
            guest = session.query(RoleModel).filter_by(name="guest").one()
            assert removed not in {p.name for p in guest.permissions}

    def test_updating_explicitly_still_restores_the_yaml(self, fresh_db):
        """``--update-existing`` is how an operator asks for the opposite."""
        with fresh_db.session() as session:
            seed_base_roles(session)

        with fresh_db.session() as session:
            guest = session.query(RoleModel).filter_by(name="guest").one()
            removed = guest.permissions[0].name
            guest.permissions = guest.permissions[1:]

        with fresh_db.session() as session:
            RoleLoader(session).load_from_yaml(
                DEFAULT_RBAC_CONFIG_PATH, update_existing=True
            )

        with fresh_db.session() as session:
            guest = session.query(RoleModel).filter_by(name="guest").one()
            assert removed in {p.name for p in guest.permissions}


class TestThePassReportsWhatItDid:
    """
    "Seeded successfully" was printed for a pass that built the whole of RBAC
    and for one that changed nothing, including after the operator edited the
    YAML.
    """

    def test_a_first_pass_reports_what_it_created(self, fresh_db):
        with fresh_db.session() as session:
            summary = seed_base_roles(session)

        assert summary.roles_created
        assert summary.permissions_created
        assert not summary.roles_left_alone

    def test_a_second_pass_reports_that_it_created_nothing(self, fresh_db):
        with fresh_db.session() as session:
            seed_base_roles(session)

        with fresh_db.session() as session:
            summary = seed_base_roles(session)

        assert not summary.roles_created
        assert not summary.permissions_created
        assert summary.roles_left_alone
        assert "left as they are" in summary.describe()


class TestASystemRoleCanBeMadeSystemAgain:
    """
    ``create_role`` writes ``is_system=False`` unconditionally, so a system
    role deleted and recreated through the admin API came back without the
    protection that stops it being deleted or edited -- and nothing could
    put it back, because seeding does not touch the fields of an existing
    role. The flag is not a setting an operator tunes; it is a statement
    that the role is part of the service.
    """

    def test_the_flag_is_restored_by_seeding(self, fresh_db):
        with fresh_db.session() as session:
            seed_base_roles(session)

        with fresh_db.session() as session:
            guest = session.query(RoleModel).filter_by(name="guest").one()
            guest.is_system = False

        with fresh_db.session() as session:
            summary = seed_base_roles(session)

        with fresh_db.session() as session:
            guest = session.query(RoleModel).filter_by(name="guest").one()
            assert guest.is_system is True
        assert "guest" in summary.roles_reprotected
        assert "system flag restored" in summary.describe()

    def test_nothing_else_about_the_role_is_touched(self, fresh_db):
        """It restores the flag, not the permissions an operator granted."""
        with fresh_db.session() as session:
            seed_base_roles(session)

        with fresh_db.session() as session:
            guest = session.query(RoleModel).filter_by(name="guest").one()
            guest.is_system = False
            removed = guest.permissions[0].name
            guest.permissions = guest.permissions[1:]

        with fresh_db.session() as session:
            seed_base_roles(session)

        with fresh_db.session() as session:
            guest = session.query(RoleModel).filter_by(name="guest").one()
            assert guest.is_system is True
            assert removed not in {p.name for p in guest.permissions}

    def test_a_role_that_is_not_a_system_role_stays_that_way(self, fresh_db):
        """Only roles the YAML calls system roles get the flag."""
        with fresh_db.session() as session:
            seed_base_roles(session)
            session.add(
                RoleModel(id="custom-1", name="editor", description="custom")
            )

        with fresh_db.session() as session:
            seed_base_roles(session)

        with fresh_db.session() as session:
            editor = session.query(RoleModel).filter_by(name="editor").one()
            assert not editor.is_system
