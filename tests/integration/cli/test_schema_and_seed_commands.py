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
from sqlalchemy import inspect

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

    def test_migrate_refuses_when_alembic_is_switched_off(
        self, populated_database
    ):
        """No revision is written for a schema built from the models.

        The profile under test runs with ``USE_ALEMBIC`` off, which is the
        branch: writing a revision here would produce a migration against a
        database that has no revision history to add it to.
        """
        app = _app_on(populated_database)
        assert app.config.get("USE_ALEMBIC") is False
        runner = FlaskCliRunner(app)

        result = runner.invoke(app.cli, ["alembic", "migrate", "add something"])

        assert result.exit_code == 1
        assert "USE_ALEMBIC is disabled" in result.output
