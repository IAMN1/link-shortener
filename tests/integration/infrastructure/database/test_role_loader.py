"""Integration tests for RBAC seeding against a real database."""

import pytest

from link_shortener.domain import ValidationError
from link_shortener.domain.policies.role_policy import (
    ROLE_DESCRIPTION_MAX_LENGTH,
)
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

    def test_a_pass_that_replaced_permissions_names_the_roles(self, fresh_db):
        """
        The one thing ``--update-existing`` is run for, and the one the
        report did not carry.

        ``roles_regranted`` was collected and never rendered, so a pass
        that put a permission back on a role said "permissions created: 0;
        roles created: 0" and nothing else -- indistinguishable from a pass
        that did nothing at all. The troubleshooting table sends an
        operator here to restore ``link:create`` on ``guest``, and this is
        the line that tells them it worked.
        """
        with fresh_db.session() as session:
            seed_base_roles(session)

        with fresh_db.session() as session:
            guest = session.query(RoleModel).filter_by(name="guest").one()
            guest.permissions = guest.permissions[1:]

        with fresh_db.session() as session:
            summary = RoleLoader(session).load_from_yaml(
                DEFAULT_RBAC_CONFIG_PATH, update_existing=True
            )

        assert [role.name for role in summary.roles_regranted] == ["guest"]
        assert "permissions replaced on: guest" in summary.describe()

    def test_a_pass_that_replaced_nothing_says_nothing_about_it(self, fresh_db):
        """
        Running the same file twice rewrites the same associations, and a
        line saying so would say something happened when nothing did --
        which is the reason ``roles_regranted`` records only real changes.
        """
        with fresh_db.session() as session:
            seed_base_roles(session)

        with fresh_db.session() as session:
            summary = RoleLoader(session).load_from_yaml(
                DEFAULT_RBAC_CONFIG_PATH, update_existing=True
            )

        assert "permissions replaced on" not in summary.describe()


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


class TestTheNameRuleStandsAtThisDoorToo:
    """``load-custom-roles`` is the second way a role is created.

    The rule about what a role may be called lived in the admin API's
    Pydantic schema and nowhere else, so a YAML file walked past it.
    Measured before the fix: a role named ``a/b`` went in, and
    ``DELETE /api/v1/admin/roles/a/b`` cannot address it -- Werkzeug's
    default converter stops at the slash -- so nothing short of SQL could
    take it out again.
    """

    def test_a_name_no_route_can_address_is_refused(self, fresh_db, tmp_path):
        bad = tmp_path / "bad-name.yaml"
        bad.write_text(
            "permissions:\n"
            "  - name: \"link:create\"\n"
            "    resource: \"link\"\n"
            "    action: \"create\"\n"
            "roles:\n"
            "  - name: \"a/b\"\n"
            "    description: \"a name no route can address\"\n"
            "    permissions: [\"link:create\"]\n"
        )

        with fresh_db.session() as session:
            with pytest.raises(ValidationError):
                RoleLoader(session).load_from_yaml(bad)

        with fresh_db.session() as session:
            assert session.query(RoleModel).filter_by(name="a/b").first() is None

    def test_the_shipped_configuration_passes_the_rule(self, fresh_db):
        """The rule must not refuse what the service itself ships."""
        with fresh_db.session() as session:
            summary = RoleLoader(session).load_from_yaml(
                DEFAULT_RBAC_CONFIG_PATH
            )

        assert sorted(summary.roles_created) == [
            "admin", "analyst", "auditor", "guest", "user",
        ]

    def test_a_description_wider_than_the_column_is_refused(
        self, fresh_db, tmp_path
    ):
        """
        The half of the rule this door was still missing. Measured on
        the running stack before the fix: ``flask db load-custom-roles``
        with a 256-character description came back
        ``sqlalchemy.exc.DataError: (psycopg.errors.StringDataRight
        Truncation) value too long for type character varying(255)`` --
        out of the driver, naming no field, where the bad name above is
        refused with a sentence. SQLite does not check the width at all,
        so the row simply went in here and the suite saw nothing.
        """
        too_wide = tmp_path / "wide-description.yaml"
        too_wide.write_text(
            "permissions:\n"
            "  - name: \"link:create\"\n"
            "    resource: \"link\"\n"
            "    action: \"create\"\n"
            "roles:\n"
            "  - name: \"wide-description\"\n"
            f"    description: \"{'d' * (ROLE_DESCRIPTION_MAX_LENGTH + 1)}\"\n"
            "    permissions: [\"link:create\"]\n"
        )

        with fresh_db.session() as session:
            with pytest.raises(ValidationError):
                RoleLoader(session).load_from_yaml(too_wide)

        with fresh_db.session() as session:
            assert session.query(RoleModel).filter_by(
                name="wide-description"
            ).first() is None


class TestWhatUpdateExistingActuallyUpdates:
    """``--update-existing`` reaches the permissions, not only the roles.

    The flag was accepted by ``load_from_yaml`` and then passed to
    ``_upsert_permission`` as a hard-coded ``False``. Both the docstring
    ("existing permissions are never modified unless ``update_existing``
    is True") and the CLI help ("Update existing roles and permissions")
    described the behaviour the code did not have -- and the command
    printed "Updated roles and permission from <file>" either way, so an
    operator editing a description saw a success and no change.
    """

    def _file(self, tmp_path, name, description):
        """A one-permission YAML file with the given description."""
        path = tmp_path / f"{name}.yaml"
        path.write_text(
            "permissions:\n"
            "  - name: \"link:create\"\n"
            "    resource: \"link\"\n"
            "    action: \"create\"\n"
            f"    description: \"{description}\"\n"
            "roles: []\n"
        )
        return path

    def test_the_flag_reaches_an_existing_permission(self, fresh_db, tmp_path):
        first = self._file(tmp_path, "first", "as it was")
        second = self._file(tmp_path, "second", "as it should be")

        with fresh_db.session() as session:
            RoleLoader(session).load_from_yaml(first)

        with fresh_db.session() as session:
            RoleLoader(session).load_from_yaml(second, update_existing=True)

        with fresh_db.session() as session:
            stored = session.query(PermissionModel).filter_by(
                name="link:create"
            ).one()
            assert stored.description == "as it should be"

    def test_without_the_flag_the_permission_is_left_alone(
        self, fresh_db, tmp_path
    ):
        """The other half of the promise, which did hold."""
        first = self._file(tmp_path, "keep-first", "as it was")
        second = self._file(tmp_path, "keep-second", "as it should not be")

        with fresh_db.session() as session:
            RoleLoader(session).load_from_yaml(first)

        with fresh_db.session() as session:
            RoleLoader(session).load_from_yaml(second)

        with fresh_db.session() as session:
            stored = session.query(PermissionModel).filter_by(
                name="link:create"
            ).one()
            assert stored.description == "as it was"


class TestAFileThatNamesSomethingTwiceIsRefusedByName:
    """
    A duplicated name in the RBAC file used to be told as somebody else's
    news.

    The upsert pass looks a name up before inserting it, but sessions are
    built with ``autoflush=False``, so the second copy's lookup does not
    see the first one pending: two rows are added and the unique index
    refuses them at the flush -- after the whole seed is assembled, and
    as an ``IntegrityError``.

    That is exactly the exception start-up seeding already has a meaning
    for. Every worker seeds at start-up, two of them race for the same
    permission, and the loser's ``IntegrityError`` is logged as the
    expected outcome it is. A duplicated name arrives wearing those
    clothes: the seed rolls back whole, the deployment comes up with an
    empty ``roles`` table and answers 401 to anonymous shortening, and
    the only line in the log says another process did the seeding.

    Measured before the guard: 0 roles and 0 permissions in the database,
    ``UNIQUE constraint failed: permissions.name`` as the only evidence.
    """

    def _file_with_a_repeated(self, section, tmp_path):
        """Write the shipped RBAC file with one entry of ``section`` twice.

        Args:
            section: Either ``"permissions"`` or ``"roles"``.
            tmp_path: Directory to write the copy into.

        Returns:
            Path to the copy.
        """
        import yaml as _yaml

        config = _yaml.safe_load(DEFAULT_RBAC_CONFIG_PATH.read_text())
        config[section].append(dict(config[section][0]))
        path = tmp_path / f"repeated_{section}.yaml"
        path.write_text(_yaml.safe_dump(config))
        return path

    @pytest.mark.parametrize("section", ["permissions", "roles"])
    def test_the_repeated_name_is_named(self, fresh_db, tmp_path, section):
        """
        The message has to carry the name, because the file ships with
        dozens of entries and the operator has to find the one.

        A ``ValidationError`` and not a bare ``ValueError``: the refusal
        travels to an operator through ``ReportingGroup``, whose
        ``REFUSALS`` names the domain's errors and not Python's. Raised as
        a ``ValueError`` it went past that door -- measured, ``flask db
        load-custom-roles`` on such a file printed a fourteen-frame
        traceback and the sentence composed here never reached the
        terminal.
        """
        path = self._file_with_a_repeated(section, tmp_path)
        repeated = __import__("yaml").safe_load(path.read_text())[section][0]

        with fresh_db.session() as session:
            with pytest.raises(ValidationError) as refusal:
                RoleLoader(session).load_from_yaml(path)

        assert repeated["name"] in str(refusal.value)

    @pytest.mark.parametrize("section", ["permissions", "roles"])
    def test_it_is_not_reported_as_a_lost_race(
        self, fresh_db, tmp_path, section
    ):
        """
        The distinction that matters: a race is an ``IntegrityError`` and
        is passed over in silence at start-up, so this must not be one.
        """
        from sqlalchemy.exc import IntegrityError

        path = self._file_with_a_repeated(section, tmp_path)

        with fresh_db.session() as session:
            with pytest.raises(ValidationError) as refusal:
                RoleLoader(session).load_from_yaml(path)

        assert not isinstance(refusal.value, IntegrityError)

    def test_the_shipped_file_repeats_nothing(self, fresh_db):
        """
        The other half, and the one that would fail loudest: the guard
        must not refuse the file the service actually ships with.
        """
        with fresh_db.session() as session:
            seed_base_roles(session)

        assert _role_permission_counts(fresh_db).get("admin", 0) > 0


class TestAPermissionTheServiceDoesNotDefine:
    """
    A name the table does not carry is refused, not dropped.

    ``PermissionModel.name.in_(names)`` returns what it finds and says
    nothing about what it did not, so a file asking for a permission that
    does not exist produced a role with none at all -- and the pass
    reported ``roles created: 1``. Measured on a live database: a role
    named ``made-up`` was created holding nothing, exit 0, while the same
    input through the admin API answers ``400 PERMISSIONS_NOT_FOUND``.
    """

    def _file_asking_for(self, tmp_path, name: str):
        """A role file naming one permission."""
        path = tmp_path / "roles.yaml"
        path.write_text(
            "permissions: []\n"
            "roles:\n"
            "  - name: \"asks-for-it\"\n"
            "    description: \"a role for the probe\"\n"
            f"    permissions: [\"{name}\"]\n"
        )
        return path

    def test_it_is_refused_by_name(self, fresh_db, tmp_path):
        with fresh_db.session() as session:
            seed_base_roles(session)

        path = self._file_asking_for(tmp_path, "nosuch:permission")

        with fresh_db.session() as session:
            with pytest.raises(ValidationError) as refusal:
                RoleLoader(session).load_from_yaml(path, update_existing=True)

        assert "nosuch:permission" in str(refusal.value)

    def test_a_permission_that_exists_is_granted(self, fresh_db, tmp_path):
        """The half that keeps the refusal from being a wall."""
        with fresh_db.session() as session:
            seed_base_roles(session)

        path = self._file_asking_for(tmp_path, "link:create")

        with fresh_db.session() as session:
            summary = RoleLoader(session).load_from_yaml(
                path, update_existing=True
            )

        assert summary.roles_created == ["asks-for-it"]

        with fresh_db.session() as session:
            made = session.query(RoleModel).filter_by(name="asks-for-it").one()
            assert [p.name for p in made.permissions] == ["link:create"]


class TestReplacingASystemRoleSaysWhichKindItWas:
    """
    This door may rewrite a system role; the report has to say it did.

    The admin API refuses -- ``PUT /api/v1/admin/roles/user/permissions``
    answers ``400 ROLE_IS_SYSTEM`` -- and this one allows it deliberately:
    it is the way back when a system role has lost a permission, which is
    what the troubleshooting table sends an operator here for. Measured
    before this: a file granting ``admin:all`` to ``user`` was applied with
    exit 0 and a line that read like any other, and every account holding
    ``user`` could then open the admin pages.
    """

    def test_the_report_names_it_as_a_system_role(self, fresh_db, tmp_path):
        with fresh_db.session() as session:
            seed_base_roles(session)

        path = tmp_path / "roles.yaml"
        path.write_text(
            "permissions: []\n"
            "roles:\n"
            "  - name: \"user\"\n"
            "    description: \"Regular registered user\"\n"
            "    permissions: [\"link:create\"]\n"
        )

        with fresh_db.session() as session:
            summary = RoleLoader(session).load_from_yaml(
                path, update_existing=True
            )

        assert "user (a system role)" in summary.describe()

    def test_a_role_of_the_operators_own_is_not_labelled(self, fresh_db, tmp_path):
        """The other half: the label has to mean something."""
        with fresh_db.session() as session:
            seed_base_roles(session)

        made = tmp_path / "made.yaml"
        made.write_text(
            "permissions: []\n"
            "roles:\n"
            "  - name: \"theirs\"\n"
            "    description: \"a role an operator made\"\n"
            "    permissions: [\"link:create\"]\n"
        )
        with fresh_db.session() as session:
            RoleLoader(session).load_from_yaml(made, update_existing=True)

        changed = tmp_path / "changed.yaml"
        changed.write_text(
            "permissions: []\n"
            "roles:\n"
            "  - name: \"theirs\"\n"
            "    description: \"a role an operator made\"\n"
            "    permissions: [\"link:view_own\"]\n"
        )
        with fresh_db.session() as session:
            summary = RoleLoader(session).load_from_yaml(
                changed, update_existing=True
            )

        assert "theirs" in summary.describe()
        assert "theirs (a system role)" not in summary.describe()
