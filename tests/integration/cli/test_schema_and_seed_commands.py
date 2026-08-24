"""The commands that build the schema, fill it, and load roles into it.

None of these seven was executed by any test: ``db init``, ``db drop``,
``db seed``, ``db load-base-roles``, ``db load-custom-roles``,
``alembic history`` and ``alembic migrate`` were reachable only by hand.
They are the commands an
operator runs on a database that has nothing in it yet, or on one that has
everything -- the two moments where a mistake costs the most.

What is checked is the database rather than the wording. ``db seed``
announces what it created from the entities it holds, not from what the
repository kept, and ``db drop`` prints its line whether or not the tables
went away, so a test reading the output alone would pass with the write
removed.
"""

import pytest
from flask.testing import FlaskCliRunner
from sqlalchemy import inspect, text

from link_shortener.infrastructure.configs.app.testing import TestingConfig
from link_shortener.infrastructure.database.manager import DatabaseManager
from link_shortener.infrastructure.database.seed import seed_base_roles


class SchemaConfig(TestingConfig):
    """Testing profile that seeds nothing on its own."""

    LOGGING_ENABLED = False
    AUDIT_ENABLED = False
    AUTO_SEED_ROLES = False


def _app_on(manager):
    """Build an application bound to an existing database manager."""
    from link_shortener.web.app_factory import create_app

    application = create_app(config=SchemaConfig())
    application.container.db_component._manager = manager
    return application


@pytest.fixture
def empty_database():
    """A connected database with no schema in it.

    ``db init`` and ``db drop`` are about the schema itself, so the fixture
    stops at ``connect()``: creating the tables here would leave the first
    command nothing to do and the assertion nothing to distinguish.
    """
    manager = DatabaseManager(
        database_url=SchemaConfig.DATABASE_URL,
        echo=False,
        database_type="sqlite",
    )
    manager.connect()

    yield manager
    manager.close()


@pytest.fixture
def populated_database():
    """A database with the schema and the base roles already in place."""
    manager = DatabaseManager(
        database_url=SchemaConfig.DATABASE_URL,
        echo=False,
        database_type="sqlite",
    )
    manager.connect()
    manager.create_tables()
    with manager.session() as session:
        seed_base_roles(session)

    yield manager
    manager.close()


def _tables(manager):
    """Names of the tables the database currently has."""
    return set(inspect(manager.engine).get_table_names())


def _roles_file(path, description):
    """Write a roles file carrying one role with the given description."""
    path.write_text(
        "permissions:\n"
        '  - name: "report:read"\n'
        '    resource: "report"\n'
        '    action: "read"\n'
        '    description: "Read the reports"\n'
        "roles:\n"
        '  - name: "report-reader"\n'
        f'    description: "{description}"\n'
        "    is_system: false\n"
        "    permissions:\n"
        '      - "report:read"\n',
        encoding="utf-8",
    )
    return path


def _role_description(app, name):
    """Read a role's description back through the repository."""
    with app.app_context():
        with app.container.get_uow_factory()(read_only=True) as uow:
            role = uow.roles.get_by_name(name)
    return role.description if role else None


def _stored_links(app):
    """Read the most recent links back through the repository."""
    with app.app_context():
        with app.container.get_uow_factory()(read_only=True) as uow:
            return uow.links.get_recent(limit=100)


class TestTheSchemaCommands:
    """``db init`` and ``db drop``: the two that touch the tables."""

    def test_init_creates_the_tables(self, empty_database):
        """The schema is built from the models."""
        app = _app_on(empty_database)
        runner = FlaskCliRunner(app)
        assert "users" not in _tables(empty_database)

        result = runner.invoke(app.cli, ["db", "init"])

        assert result.exit_code == 0, result.output
        assert {"users", "urls", "roles"} <= _tables(empty_database)

    def test_init_refuses_when_alembic_owns_the_schema(self, empty_database):
        """With ``USE_ALEMBIC`` on, the command declines and writes nothing.

        The two ways of building a schema must not be mixed: tables created
        from the models carry no revision, so a later ``alembic upgrade``
        tries to create what is already there.
        """
        app = _app_on(empty_database)
        app.config["USE_ALEMBIC"] = True
        runner = FlaskCliRunner(app)

        result = runner.invoke(app.cli, ["db", "init"])

        assert result.exit_code == 1
        assert "alembic upgrade head" in result.output
        assert _tables(empty_database) == set()

    def test_drop_removes_the_tables(self, populated_database):
        """With ``--yes`` the schema goes away."""
        app = _app_on(populated_database)
        runner = FlaskCliRunner(app)
        assert "users" in _tables(populated_database)

        result = runner.invoke(app.cli, ["db", "drop", "--yes"])

        assert result.exit_code == 0, result.output
        assert _tables(populated_database) == set()

    def test_drop_without_the_flag_asks_and_keeps_them(self, populated_database):
        """Answering the prompt with "no" leaves the database alone."""
        app = _app_on(populated_database)
        runner = FlaskCliRunner(app)
        before = _tables(populated_database)

        result = runner.invoke(app.cli, ["db", "drop"], input="n\n")

        assert result.exit_code != 0
        assert "Are you sure" in result.output
        assert _tables(populated_database) == before

    def test_drop_refuses_when_alembic_owns_the_schema(self, populated_database):
        """``--yes`` does not override the flag; the tables stay."""
        app = _app_on(populated_database)
        app.config["USE_ALEMBIC"] = True
        runner = FlaskCliRunner(app)
        before = _tables(populated_database)

        result = runner.invoke(app.cli, ["db", "drop", "--yes"])

        assert result.exit_code == 1
        assert "alembic downgrade base" in result.output
        assert _tables(populated_database) == before


class TestSeeding:
    """``db seed``: the links an operator makes to have something to look at."""

    def test_seed_writes_the_links(self, populated_database):
        """The requested number of links is in the database afterwards."""
        app = _app_on(populated_database)
        runner = FlaskCliRunner(app)

        result = runner.invoke(app.cli, ["db", "seed", "--count", "3"])

        assert result.exit_code == 0, result.output
        assert "Created 3 test links" in result.output
        assert len(_stored_links(app)) == 3

    def test_seed_counts_what_was_already_there(self, populated_database):
        """A second run creates nothing and says so.

        Seeding shortens a fixed list of URLs, and the service deduplicates
        by hash, so the second pass finds every one of them already stored.
        """
        app = _app_on(populated_database)
        runner = FlaskCliRunner(app)
        runner.invoke(app.cli, ["db", "seed", "--count", "2"])

        result = runner.invoke(app.cli, ["db", "seed", "--count", "2"])

        assert result.exit_code == 0, result.output
        assert "Created 0 test links" in result.output
        assert "2 of the requested URLs already existed" in result.output
        assert len(_stored_links(app)) == 2


class TestRoleLoading:
    """``db load-base-roles`` and ``db load-custom-roles``."""

    def test_base_roles_land_in_the_database(self, empty_database):
        """The roles named in the bundled YAML exist afterwards."""
        empty_database.create_tables()
        app = _app_on(empty_database)
        runner = FlaskCliRunner(app)

        result = runner.invoke(app.cli, ["db", "load-base-roles"])

        assert result.exit_code == 0, result.output
        with app.app_context():
            with app.container.get_uow_factory()(read_only=True) as uow:
                names = {role.name for role in uow.roles.list_all()}
        assert {"guest", "user", "admin"} <= names

    def test_a_custom_file_adds_its_role(self, populated_database, tmp_path):
        """A role written in a file of one's own is created."""
        roles_file = tmp_path / "extra-roles.yaml"
        roles_file.write_text(
            "permissions:\n"
            '  - name: "report:read"\n'
            '    resource: "report"\n'
            '    action: "read"\n'
            '    description: "Read the reports"\n'
            "roles:\n"
            '  - name: "report-reader"\n'
            '    description: "Reads reports and nothing else"\n'
            "    is_system: false\n"
            "    permissions:\n"
            '      - "report:read"\n',
            encoding="utf-8",
        )
        app = _app_on(populated_database)
        runner = FlaskCliRunner(app)

        result = runner.invoke(
            app.cli, ["db", "load-custom-roles", str(roles_file)]
        )

        assert result.exit_code == 0, result.output
        with app.app_context():
            with app.container.get_uow_factory()(read_only=True) as uow:
                reader = uow.roles.get_by_name("report-reader")
        assert reader is not None
        assert {p.name for p in reader.permissions} == {"report:read"}

    def test_an_existing_role_is_left_alone_without_the_flag(
        self, populated_database, tmp_path
    ):
        """A second load does not overwrite what the first one created.

        ``--update-existing`` is the only thing separating the two
        behaviours, so both are checked: a body ignoring the flag passes
        any check that loads a file once.
        """
        first = _roles_file(tmp_path / "first.yaml", "Reads reports")
        second = _roles_file(tmp_path / "second.yaml", "Reads everything")
        app = _app_on(populated_database)
        runner = FlaskCliRunner(app)
        runner.invoke(app.cli, ["db", "load-custom-roles", str(first)])

        result = runner.invoke(app.cli, ["db", "load-custom-roles", str(second)])

        assert result.exit_code == 0, result.output
        assert _role_description(app, "report-reader") == "Reads reports"

    def test_the_flag_updates_the_existing_role(
        self, populated_database, tmp_path
    ):
        """With the flag, the description written second is the one kept."""
        first = _roles_file(tmp_path / "first.yaml", "Reads reports")
        second = _roles_file(tmp_path / "second.yaml", "Reads everything")
        app = _app_on(populated_database)
        runner = FlaskCliRunner(app)
        runner.invoke(app.cli, ["db", "load-custom-roles", str(first)])

        result = runner.invoke(
            app.cli,
            ["db", "load-custom-roles", str(second), "--update-existing"],
        )

        assert result.exit_code == 0, result.output
        assert _role_description(app, "report-reader") == "Reads everything"

    def test_a_missing_file_is_refused(self, populated_database, tmp_path):
        """Click checks the path before anything opens a session."""
        app = _app_on(populated_database)
        runner = FlaskCliRunner(app)

        result = runner.invoke(
            app.cli, ["db", "load-custom-roles", str(tmp_path / "absent.yaml")]
        )

        assert result.exit_code == 2
        assert "does not exist" in result.output


class TestAlembicGroup:
    """The two commands of that group nothing executed."""

    def test_history_lists_the_revisions(self, populated_database):
        """The revision that creates the schema is named in the output."""
        app = _app_on(populated_database)
        runner = FlaskCliRunner(app)

        result = runner.invoke(app.cli, ["alembic", "history"])

        assert result.exit_code == 0, result.output
        assert "0001" in result.output

    # ``alembic migrate`` refusing while ``USE_ALEMBIC`` is off was
    # asserted here as well, for that one command and against
    # ``result.output``. It is held in ``test_commands.py`` by
    # ``TestTheAlembicGroupHonoursTheFlag``, which puts the same question
    # to all three commands that change a schema and reads the stream the
    # refusal is actually written to -- so this was the same claim,
    # narrower, and a second place to remember when the rule changes.


class AuditedSchemaConfig(SchemaConfig):
    """The same profile with the audit trail wired up."""

    AUDIT_ENABLED = True


def _audited_app_on(manager):
    """An application that records what its commands do."""
    from link_shortener.web.app_factory import create_app

    application = create_app(config=AuditedSchemaConfig())
    application.container.db_component._manager = manager
    return application


def _recorded(app):
    """The security events written so far, oldest first.

    Read out of the table the counting logger writes to, rather than
    asserted against a mock: what puts an event in front of the charts is
    the row, and a call to some other logger would satisfy a mock and
    leave the table empty.

    The table holds the kind and the moment and nothing else -- it is the
    counter behind the charts, not the journal. What a record *says* is
    checked where it can be seen, in
    ``test_the_record_names_what_the_role_grants`` below.
    """
    with app.app_context():
        with app.container.get_db_manager().session() as session:
            return [
                row[0]
                for row in session.execute(
                    text(
                        "SELECT event_type FROM security_events "
                        "ORDER BY occurred_at, id"
                    )
                ).all()
            ]


class TestLoadingRolesLeavesARecord:
    """A role brought in from a file is a role somebody was granted.

    ``POST /api/v1/admin/roles`` writes ``ROLE_CREATED``; this door wrote
    nothing, so an operator could add a role carrying
    ``admin:manage_users`` and the journal would hold no trace of where it
    came from. The rule the vocabulary admits events by is the act that
    changes who may do what, and creating a role with permissions on it is
    that act whichever door it comes through.
    """

    def test_a_role_from_the_file_is_recorded(self, populated_database, tmp_path):
        app = _audited_app_on(populated_database)
        runner = FlaskCliRunner(app)

        result = runner.invoke(
            app.cli,
            ["db", "load-custom-roles", str(_roles_file(tmp_path / "r.yaml", "Reads"))],
        )

        assert result.exit_code == 0, result.output
        assert _recorded(app) == ["ROLE_CREATED"]

    def test_the_record_names_what_the_role_grants(
        self, populated_database, tmp_path
    ):
        """The permissions, not just the name.

        A record saying only that "report-reader" appeared answers half
        the question an investigator arrives with; what it can do is the
        other half. Asserted against the logger because that is where this
        is visible: ``security_events`` keeps the kind and the moment,
        being the counter behind the charts rather than the journal.

        The permissions are read off the stored role rather than off the
        file, so one the loader resolved to an existing row is reported as
        it actually landed.
        """
        from unittest.mock import MagicMock

        from link_shortener.application.ports.logger.audit import AuditLogger
        from link_shortener.infrastructure.cli.commands.database import (
            load_custom_roles_from_cfg,
        )

        # Typed, so a misspelt method name is an error rather than a new
        # attribute the mock invents and the assertion below then checks
        # against nothing.
        audit = MagicMock(spec=AuditLogger)

        load_custom_roles_from_cfg(
            populated_database,
            str(_roles_file(tmp_path / "r.yaml", "Reads")),
            audit,
        )

        audit.log_role_created.assert_called_once_with(
            role="report-reader", permissions=["report:read"]
        )

    def test_a_second_run_that_creates_nothing_records_nothing(
        self, populated_database, tmp_path
    ):
        """Loading is idempotent, and an event says something happened."""
        app = _audited_app_on(populated_database)
        runner = FlaskCliRunner(app)
        roles_file = _roles_file(tmp_path / "r.yaml", "Reads")

        runner.invoke(app.cli, ["db", "load-custom-roles", str(roles_file)])
        before = len(_recorded(app))
        runner.invoke(app.cli, ["db", "load-custom-roles", str(roles_file)])

        assert len(_recorded(app)) == before

    def test_seeding_the_base_roles_is_not_recorded(self, populated_database):
        """The command next door writes nothing, deliberately.

        Seeding is excluded by the same rule that admits the command
        above: the installation putting its own four roles in place is
        not somebody being granted anything, and a journal that records
        it buries the entries that matter under every deployment.
        """
        app = _audited_app_on(populated_database)
        runner = FlaskCliRunner(app)

        result = runner.invoke(app.cli, ["db", "load-base-roles"])

        assert result.exit_code == 0, result.output
        assert _recorded(app) == []


class TestRegrantingARoleLeavesARecord:
    """``--update-existing`` replaces what a role grants, on the record.

    The widest-reaching act the vocabulary has a name for: every account
    wearing the role is moved at once, and none of their accounts is
    touched, so an investigator asking why an account could suddenly do
    something finds nothing against the account. Measured before this
    existed: one command took ``report:read`` off a role and gave it
    ``admin:manage_users``, and the journal held nothing.

    ``ROLE_CREATED`` was recorded here already, which made the silence
    worse rather than better -- a reader seeing the CLI write about a
    role being created would take it for a door that reports itself.
    """

    @staticmethod
    def _file(path, name, permission):
        """A roles file granting one named permission."""
        path.write_text(
            "permissions:\n"
            '  - name: "report:read"\n'
            '    resource: "report"\n'
            '    action: "read"\n'
            '    description: "Read the reports"\n'
            '  - name: "admin:manage_users"\n'
            '    resource: "admin"\n'
            '    action: "manage_users"\n'
            '    description: "Manage users"\n'
            "roles:\n"
            f'  - name: "{name}"\n'
            '    description: "A role under test"\n'
            "    is_system: false\n"
            "    permissions:\n"
            f'      - "{permission}"\n',
            encoding="utf-8",
        )
        return path

    def test_a_role_that_gains_a_permission_is_recorded(
        self, populated_database, tmp_path
    ):
        app = _audited_app_on(populated_database)
        runner = FlaskCliRunner(app)
        runner.invoke(
            app.cli,
            ["db", "load-custom-roles",
             str(self._file(tmp_path / "a.yaml", "regranted", "report:read"))],
        )

        result = runner.invoke(
            app.cli,
            ["db", "load-custom-roles",
             str(self._file(tmp_path / "b.yaml", "regranted", "admin:manage_users")),
             "--update-existing"],
        )

        assert result.exit_code == 0, result.output
        assert _recorded(app) == ["ROLE_CREATED", "ROLE_PERMISSIONS_CHANGED"]

    def test_the_record_carries_what_was_taken_and_given(
        self, populated_database, tmp_path
    ):
        """Before and after, not just the fact of a change.

        Asserted against the logger because that is where this is
        visible: ``security_events`` keeps the kind and the moment.
        """
        from unittest.mock import MagicMock

        from link_shortener.application.ports.logger.audit import AuditLogger
        from link_shortener.infrastructure.cli.commands.database import (
            load_custom_roles_from_cfg,
        )

        load_custom_roles_from_cfg(
            populated_database,
            str(self._file(tmp_path / "a.yaml", "regranted", "report:read")),
            MagicMock(spec=AuditLogger),
        )

        audit = MagicMock(spec=AuditLogger)
        load_custom_roles_from_cfg(
            populated_database,
            str(self._file(tmp_path / "b.yaml", "regranted", "admin:manage_users")),
            audit,
            update_existing=True,
        )

        audit.log_role_permissions_changed.assert_called_once_with(
            role="regranted",
            permissions_before=["report:read"],
            permissions_after=["admin:manage_users"],
            holders=0,
        )

    def test_running_the_same_file_again_records_nothing(
        self, populated_database, tmp_path
    ):
        """The associations are rewritten either way; the grant is not.

        Without this the second run of an unchanged file would file a
        change against every role in it, and a journal that reports
        changes nobody made is one an investigator stops reading.
        """
        app = _audited_app_on(populated_database)
        runner = FlaskCliRunner(app)
        roles_file = self._file(tmp_path / "a.yaml", "steady", "report:read")
        runner.invoke(app.cli, ["db", "load-custom-roles", str(roles_file)])
        before = len(_recorded(app))

        runner.invoke(
            app.cli,
            ["db", "load-custom-roles", str(roles_file), "--update-existing"],
        )

        assert len(_recorded(app)) == before

    def test_without_the_flag_nothing_is_replaced_and_nothing_recorded(
        self, populated_database, tmp_path
    ):
        """The plain run leaves an existing role alone, as it always did."""
        app = _audited_app_on(populated_database)
        runner = FlaskCliRunner(app)
        runner.invoke(
            app.cli,
            ["db", "load-custom-roles",
             str(self._file(tmp_path / "a.yaml", "untouched", "report:read"))],
        )
        before = len(_recorded(app))

        runner.invoke(
            app.cli,
            ["db", "load-custom-roles",
             str(self._file(tmp_path / "b.yaml", "untouched", "admin:manage_users"))],
        )

        assert len(_recorded(app)) == before
        with app.app_context():
            with app.container.get_uow_factory()(read_only=True) as uow:
                role = uow.roles.get_by_name("untouched")
        assert [p.name for p in role.permissions] == ["report:read"]
