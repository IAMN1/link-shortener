"""The baseline migration has to actually build a database.

Nothing exercised this before, and it was broken: the chain this baseline
replaced dropped a foreign key by the name PostgreSQL invents for it, while
the revision that created the key left it unnamed. On SQLite -- the default
of the documented local setup -- there was no such name, so a fresh database
stopped part-way and could not be built by migrations at all. It went
unnoticed because every other test builds the schema with ``create_all``
from the models, which never runs a revision.

``flask alembic upgrade head`` is the third command under "Run it" in the
quick start -- the guide numbers no steps, so it is named by what it is --
and so this is the path a clone takes on its first run. Tested against SQLite because that is what a
developer gets out of the box; PostgreSQL-only behaviour belongs in
``tests/integration/docker/``.
"""

import json
import os
import sqlite3
import subprocess
import sys

import pytest

from link_shortener.infrastructure.cli.commands.alembic import (
    AlembicCommands, _project_root
)


# Column order of PRAGMA foreign_key_list.
ON_DELETE = 6


@pytest.fixture
def database(tmp_path):
    """Path and URL of a database file that does not exist yet."""
    path = tmp_path / "migrated.db"
    return path, f"sqlite:///{path}"


def tables(path):
    """Return the table names the database currently has.

    Args:
        path: Path to the SQLite file.

    Returns:
        Set of table names.
    """
    connection = sqlite3.connect(path)
    try:
        return {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        connection.close()


def indexes(path, table):
    """Return the indexes a table carries, with the columns of each.

    Args:
        path: Path to the SQLite file.
        table: Table to inspect.

    Returns:
        Mapping of index name to the list of columns it covers, in order.
    """
    connection = sqlite3.connect(path)
    try:
        found = {}
        for row in connection.execute(f"PRAGMA index_list('{table}')"):
            name = row[1]
            found[name] = [
                column[2]
                for column in connection.execute(f"PRAGMA index_info('{name}')")
            ]
        return found
    finally:
        connection.close()


def foreign_keys(path, table):
    """Return the foreign keys a table declares.

    Args:
        path: Path to the SQLite file.
        table: Table to inspect.

    Returns:
        List of PRAGMA rows.
    """
    connection = sqlite3.connect(path)
    try:
        return list(connection.execute(f"PRAGMA foreign_key_list({table})"))
    finally:
        connection.close()


class TestMigrationChain:
    """From nothing to head, and back."""

    def test_a_fresh_database_reaches_head(self, database):
        """The whole point: an empty file becomes a usable schema.

        Asserted on the marker rather than on a revision number. The number
        was ``0001`` while there was one revision, and a test naming it had
        to be edited by whoever added the second -- an edit that reads like
        housekeeping and is the only thing standing between "we reached the
        latest revision" and "we reached the revision this test remembers".
        """
        path, url = database

        ok, output = AlembicCommands.upgrade("head", database_url=url)
        assert ok, output

        ok, current = AlembicCommands.status(database_url=url)
        assert ok, current
        assert "(head)" in current, current

    def test_the_expected_tables_exist_afterwards(self, database):
        """A migration that runs but builds nothing would still "pass"."""
        path, url = database
        ok, output = AlembicCommands.upgrade("head", database_url=url)
        assert ok, output

        assert {
            "urls", "users", "roles", "permissions",
            "role_permissions", "user_roles", "refresh_sessions",
            "email_verifications",
        } <= tables(path)

    def test_the_folded_days_can_be_read_by_day_without_a_link(self, database):
        """
        The service-wide daily chart filters ``link_visit_days`` on ``day``
        alone, and the primary key leads with ``link_id`` -- which a
        composite index cannot serve without its leading column. Every such
        read was a full scan of the table that exists to make the long
        range cheap, and it grows by one row per link per day forever.

        Asserted against the built schema rather than the model, because
        the two are separately written and have disagreed before: this
        project keeps one revision and edits it in place, so a column or
        an index added to a model reaches a deployment only if the
        revision is edited too.
        """
        path, url = database
        ok, output = AlembicCommands.upgrade("head", database_url=url)
        assert ok, output

        covering_day = [
            name for name, columns in indexes(path, "link_visit_days").items()
            if columns[:1] == ["day"]
        ]

        assert covering_day, indexes(path, "link_visit_days")

    def test_links_are_left_pointing_at_their_owner_s_deletion(self, database):
        """The cascade is a decision about data, not a detail of the schema.

        Links do not outlive the account that made them, and there is no
        recovery. Asserted against the built database rather than against
        the revision's source, because the two have disagreed: the code that
        set this up reported success on PostgreSQL while failing outright on
        SQLite, and only the schema itself tells them apart.
        """
        path, url = database
        ok, output = AlembicCommands.upgrade("head", database_url=url)
        assert ok, output

        keys = foreign_keys(path, "urls")

        owner_keys = [k for k in keys if k[3] == "owner_id"]
        assert owner_keys, f"no foreign key on owner_id: {keys}"
        assert owner_keys[0][ON_DELETE] == "CASCADE"

    def test_the_baseline_can_be_undone_and_redone(self, database):
        """A downgrade nobody runs is a downgrade nobody knows is broken."""
        path, url = database
        ok, output = AlembicCommands.upgrade("head", database_url=url)
        assert ok, output

        ok, output = AlembicCommands.downgrade("base", database_url=url)
        assert ok, output
        assert tables(path) == {"alembic_version"}

        ok, output = AlembicCommands.upgrade("head", database_url=url)
        assert ok, output
        assert "urls" in tables(path)
        assert foreign_keys(path, "urls")[0][ON_DELETE] == "CASCADE"

    def test_migrations_land_in_the_database_they_were_given(
        self, database, tmp_path, monkeypatch
    ):
        """The handoff decides the target, not the ambient environment.

        Alembic runs in a subprocess and would otherwise rebuild its own
        configuration from whatever happens to be exported -- so the
        environment here names a different database, and the point is that
        it stays untouched. Without that second file the assertions held
        for any working migration at all.
        """
        path, url = database
        decoy = tmp_path / "ambient.db"
        monkeypatch.setenv("FLASK_ENV", "production")
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{decoy}")

        ok, output = AlembicCommands.upgrade("head", database_url=url)
        assert ok, output

        assert path.exists()
        assert path.stat().st_size > 0
        assert not decoy.exists()


# Everything that decides which database a subprocess opens. Dropped
# before each run, and put back only by the test that means it: the suite
# is also run with DATABASE_URL and friends exported -- one of the three
# control runs does exactly that -- and a test that inherits them measures
# that shell instead of what it set: with
# DATABASE_URL=postgresql://prod/real exported, the refusal test stops
# refusing and goes looking for psycopg2.
AMBIENT_DATABASE_VARS = (
    "FLASK_ENV",
    "DATABASE_URL",
    "DATABASE_TYPE",
    "DATABASE_NAME",
    "DATABASE_USER",
    "DATABASE_PASSWORD",
    "DATABASE_HOST",
    "DATABASE_PORT",
    AlembicCommands.HANDOFF_ENV_VAR,
)


def bare_alembic(*args, **env):
    """
    Run alembic the way an operator does, with no caller to inherit from.

    ``AlembicCommands`` cannot stand in for this: it hands the URL over
    through the environment, which is precisely the branch these tests are
    not exercising. The variables passed here are set for real, so they
    outrank the repository's ``.env`` under the documented precedence --
    which, together with the clearing above, is what keeps the outcome the
    same on any machine.

    Args:
        *args: Arguments for the alembic CLI.
        **env: Environment variables to set for the run.

    Returns:
        The completed subprocess.
    """
    environment = os.environ.copy()
    for name in AMBIENT_DATABASE_VARS:
        environment.pop(name, None)
    environment.update(env)

    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        capture_output=True,
        text=True,
        env=environment,
        cwd=str(_project_root()),
        encoding="utf-8",
        errors="replace",
    )


class TestARunWithNoCallerToInheritFrom:
    """``alembic upgrade head`` typed into a shell, which nothing tested.

    Every test above hands the URL over, so the branch that resolves one
    from the configuration was never executed by the suite -- and that is
    the branch a recovery uses, when the application that would otherwise
    launch the migration is the thing that will not start.
    """

    def test_it_migrates_a_configuration_the_application_could_not_start_on(
        self, tmp_path
    ):
        """A limit on submitted links must not stop a schema being built.

        ``MAX_URL_LENGTH`` above 2048 is refused by ``validate()`` and read
        by nothing a migration does. It stands in here for the mail
        server, the domain and the secrets that were measured doing the
        same.
        """
        path = tmp_path / "bare.db"

        result = bare_alembic(
            "upgrade", "head",
            FLASK_ENV="production",
            DATABASE_URL=f"sqlite:///{path}",
            MAX_URL_LENGTH="99999",
        )

        assert result.returncode == 0, result.stderr
        assert "urls" in tables(path)

    def test_a_refusal_is_reported_rather_than_raised(self):
        """What the operator sees when the settings are unusable.

        A traceback ending inside the configuration factory reads as a bug
        in the tool. The refusal has to name the way past itself instead,
        because a migration is one of the ways out of a broken deployment.

        ``FLASK_ENV`` is pinned along with the bad setting: without it the
        run inherits whatever the developer exports, and under ``testing``
        -- where ``DATABASE_TYPE`` is a property no variable can move --
        this passed for the wrong reason.
        """
        result = bare_alembic(
            "upgrade", "head", FLASK_ENV="production", DATABASE_TYPE="mysql"
        )

        assert result.returncode != 0
        assert "Traceback" not in result.stderr, result.stderr
        assert "Unsupported DATABASE_TYPE" in result.stderr
        assert AlembicCommands.HANDOFF_ENV_VAR in result.stderr

    def test_it_says_which_database_it_is_about_to_change(self, tmp_path):
        """The command names the database it is about to change.

        Which matters most when a handoff is in play: an
        ``ALEMBIC_DATABASE_URL`` left over from an earlier command sends
        the migration somewhere else and reports the same success. The
        password is masked, because this line goes into deployment logs.
        """
        path = tmp_path / "announced.db"

        result = bare_alembic(
            "upgrade", "head",
            FLASK_ENV="production",
            DATABASE_URL=f"sqlite:///{path}",
        )

        assert result.returncode == 0, result.stderr
        assert f"Database: sqlite:///{path}" in result.stderr

    def test_the_engine_it_builds_is_given_the_configured_bounds(
        self, tmp_path
    ):
        """Built where nothing else can see it, so nothing else checked it.

        ``migration_connect_args`` is unit-tested, but a value that is
        computed and then not passed leaves those tests green while the
        migration waits on an unreachable server for as long as the
        operating system lets it. Asked here of ``env.py`` itself, by
        replacing the engine factory before alembic imports it -- in a
        subprocess, because ``env.py`` reconfigures logging for whatever
        process runs it.
        """
        probe = tmp_path / "probe.py"
        probe.write_text(
            "import json, sys, sqlalchemy\n"
            "def fake(section, prefix='sqlalchemy.', **kwargs):\n"
            "    print('ARGS ' + json.dumps(kwargs.get('connect_args')))\n"
            "    raise SystemExit(0)\n"
            "sqlalchemy.engine_from_config = fake\n"
            "from alembic import command\n"
            "from alembic.config import Config\n"
            "command.upgrade(Config(sys.argv[1]), 'head')\n",
            encoding="utf-8",
        )
        ini = str(_project_root() / "alembic.ini")

        environment = os.environ.copy()
        for name in AMBIENT_DATABASE_VARS:
            environment.pop(name, None)
        environment.update(
            {
                AlembicCommands.HANDOFF_ENV_VAR: (
                    "postgresql+psycopg://u:p@h:5432/db"
                ),
                "DATABASE_CONNECT_TIMEOUT": "4",
                "DATABASE_STATEMENT_TIMEOUT": "7",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )

        result = subprocess.run(
            [sys.executable, str(probe), ini],
            capture_output=True, text=True, env=environment,
            cwd=str(_project_root()), encoding="utf-8", errors="replace",
        )

        line = [
            l for l in result.stdout.splitlines() if l.startswith("ARGS ")
        ]
        assert line, f"stdout={result.stdout!r} stderr={result.stderr!r}"

        passed = json.loads(line[0][len("ARGS "):])
        assert passed["connect_timeout"] == 4
        assert passed["options"] == "-c statement_timeout=7000"

    def test_it_does_not_repeat_a_target_the_caller_already_announced(
        self, tmp_path
    ):
        """``flask alembic`` prints ``Database:`` itself before it shells out.

        Printing again from inside would put the same line twice into
        every deployment log, which is how a line stops being read.
        """
        path = tmp_path / "handed.db"

        ok, output = AlembicCommands.upgrade(
            "head", database_url=f"sqlite:///{path}"
        )

        assert ok, output
        assert "Database:" not in output
