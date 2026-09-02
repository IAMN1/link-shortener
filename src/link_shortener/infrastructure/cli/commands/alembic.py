import os
# Alembic is run as a subprocess on purpose; see _run below.
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Optional

from link_shortener.infrastructure.configs.app import migration_url


ALEMBIC_DISABLED = (
    "USE_ALEMBIC is disabled. The schema is managed from the models -- use "
    "'flask db init' to create it and 'flask db drop' to remove it."
)
"""What every command that would change the schema says when it may not.

Written once because it is said twice: the ``alembic`` group refuses
through ``_require_alembic_enabled``, ``db migrate`` refuses through
``commands.database.migrate_db``, and the two had drifted into different
sentences with different exit codes -- one of them 0.
"""


def _project_root() -> Path:
    """
    Locate the directory holding ``alembic.ini``.

    Alembic resolves ``script_location`` relative to the working directory,
    so without an explicit one the child inherits the operator's shell. That
    is not merely fragile -- running the command from ``src/`` failed with
    "No 'script_location' key found", and running it from a directory that
    happens to contain another ``alembic.ini`` executed *that* project's
    ``env.py``, with this process's environment handed to it.

    Two places are searched: upwards from this module, which answers in a
    source checkout, and upwards from the working directory, which is what
    an installed copy needs -- in the image the package is imported from
    ``site-packages``, and no parent of this file holds an ``alembic.ini``.

    Returns:
        Directory containing ``alembic.ini``.

    Raises:
        FileNotFoundError: When neither search finds one, naming both places
            that were tried -- the counted path silently produced a wrong
            answer instead.
    """
    starts = [Path(__file__).resolve(), Path.cwd().resolve()]
    for start in starts:
        for candidate in [start, *start.parents]:
            if (candidate / "alembic.ini").is_file():
                return candidate

    raise FileNotFoundError(
        "alembic.ini not found above "
        f"{starts[0]} or {starts[1]} -- run the command from the directory "
        "holding it, or install the project so that it ships alongside"
    )


class AlembicCommands:
    """Alembic migration management commands."""

    HANDOFF_ENV_VAR = migration_url.HANDOFF_ENV_VAR
    """Variable ``migrations/env.py`` reads the caller's database URL from.

    Taken from the module that reads it rather than spelled out again: the
    two ends of a handoff that disagree on the name do not fail, they
    silently stop handing anything over.

    Alembic runs in a subprocess, and a subprocess inherits the ambient
    environment rather than the configuration of the application that
    launched it. Left to itself ``env.py`` resolves a profile from that
    environment, which does not carry the caller's: nothing exports
    ``FLASK_ENV``, so a suite running under ``testing`` -- the profile that
    pins an in-memory database precisely so a test cannot reach a real one
    -- would have its migrations resolve ``development`` from ``.env`` and
    land on the developer's own file.
    """

    @staticmethod
    def _run_alembic(
        *args: str, database_url: Optional[str] = None
    ) -> subprocess.CompletedProcess:
        """
        Run an alembic command in a subprocess.

        Args:
            *args: Arguments forwarded to the alembic CLI.
            database_url: URL the caller is already configured with. Handed
                to ``migrations/env.py`` so that the subprocess targets the
                caller's database instead of re-deriving one. ``None`` leaves
                ``env.py`` to resolve it, which is what a bare shell
                invocation needs.

        Returns:
            The completed subprocess.
        """
        env = os.environ.copy()
        if database_url:
            env[AlembicCommands.HANDOFF_ENV_VAR] = database_url
        else:
            # An inherited value would otherwise decide where a command with
            # no explicit target writes.
            env.pop(AlembicCommands.HANDOFF_ENV_VAR, None)

        # An argument list, no shell: there is nothing to interpolate.
        return subprocess.run(  # nosec B603
            [sys.executable, "-m", "alembic", *args],
            capture_output=True,
            text=True,
            env=env,
            # Pin the working directory: alembic resolves script_location
            # from it, so otherwise the operator's shell chooses which
            # migrations run.
            cwd=str(_project_root()),
            # Decode explicitly. With `text=True` alone the codec comes from
            # the ambient locale, and under LC_ALL=C a revision message in
            # Cyrillic made the command die of UnicodeDecodeError instead of
            # reporting migration status.
            encoding="utf-8",
            errors="replace",
        )

    @staticmethod
    def _answer(
        result: subprocess.CompletedProcess,
        empty: str,
        both_streams: bool = False,
    ) -> tuple[bool, str]:
        """
        Turn a finished alembic run into the pair every command returns.

        Written once because it was written six times and only two of the
        copies were right. Alembic reports a configuration failure on
        *stdout* -- measured: ``No 'script_location' key found`` arrives
        there with an empty stderr and exit 255 -- so the four copies that
        read ``result.stderr`` alone answered a literal ``"Error: "``.
        ``status`` and ``history`` had been fixed for exactly that case,
        and the reason was written down in ``status``; the fix stayed
        where it was typed while ``upgrade``, which is what ``flask
        alembic upgrade`` and ``flask db migrate`` both run, went on
        losing the sentence naming what was wrong.

        Args:
            result: The finished subprocess.
            empty: What to say when the run succeeded quietly.
            both_streams: Join stderr onto stdout for the success text.
                Alembic narrates an upgrade on stderr ("Running upgrade
                X -> Y"), so without it the report is the same whether
                the whole schema was created or nothing was.

        Returns:
            Tuple of (success, output).
        """
        if result.returncode != 0:
            return False, f"Error: {result.stderr or result.stdout}".strip()

        if both_streams:
            return True, (result.stdout + result.stderr).strip() or empty

        return True, result.stdout or empty

    @staticmethod
    def status(database_url: Optional[str] = None) -> tuple[bool, str]:
        """Show current migration status, and say whether it is current.

        ``alembic current`` prints the revision the database is on and
        appends ``(head)`` when nothing is pending. That parenthesis was
        the whole of the answer: measured on a database at ``0001`` with
        ``0002`` on disk, the command printed ``0001``, and at ``0001``
        with nothing pending it printed ``0001 (head)``. An operator or a
        deployment log asking "is the schema current" had to notice a
        missing word.

        So the head is asked for as well and the two are compared. The
        exit code stays zero either way: being behind is the answer this
        command exists to give, not a failure of it -- it is run *before*
        an upgrade, and a non-zero exit would make the ordinary case look
        broken to every script that runs it.

        Args:
            database_url: URL of the database to report on.

        Returns:
            Tuple of (success, output).
        """
        current = AlembicCommands._answer(
            AlembicCommands._run_alembic("current", database_url=database_url),
            empty="No migrations applied.",
        )
        if not current[0]:
            return current

        heads = AlembicCommands._run_alembic("heads", database_url=database_url)
        if heads.returncode != 0:
            # The revision is still worth printing; what could not be
            # worked out is whether anything is waiting behind it.
            return True, (
                f"{current[1]}\n"
                "Could not read the head revision, so whether anything is "
                "pending is unknown."
            )

        head_ids = {
            line.split()[0]
            for line in heads.stdout.splitlines()
            if line.strip() and not line.startswith("Database:")
        }
        applied = {
            line.split()[0]
            for line in current[1].splitlines()
            if line.strip() and not line.startswith("Database:")
            and not line.startswith("No migrations")
        }
        pending = head_ids - applied
        if pending:
            return True, (
                f"{current[1]}\n"
                f"Behind: {', '.join(sorted(pending))} "
                f"{'is' if len(pending) == 1 else 'are'} on disk and not "
                "applied. Run 'flask alembic upgrade head'."
            )
        if not applied:
            # A database carrying no revision at all is not "up to date",
            # whatever the head list says -- and with no revisions on disk
            # either, the two sentences together read as a contradiction.
            # The `empty` text above already says the whole of it.
            return current
        return True, f"{current[1]}\nUp to date."

    @staticmethod
    def history(
        revision: Optional[str] = None, database_url: Optional[str] = None
    ) -> tuple[bool, str]:
        """Show migration history.

        Args:
            revision: Show history starting from this revision.
            database_url: URL of the database to report on.

        Returns:
            Tuple of (success, output).
        """
        args = ["history"]
        if revision:
            args.extend(["-r", revision])
        return AlembicCommands._answer(
            AlembicCommands._run_alembic(*args, database_url=database_url),
            empty="No migration history.",
        )

    @staticmethod
    def upgrade(
        target: str = "head", database_url: Optional[str] = None
    ) -> tuple[bool, str]:
        """Apply migrations to target revision.

        Args:
            target: Revision to upgrade to.
            database_url: URL of the database to migrate.

        Returns:
            Tuple of (success, output).
        """
        return AlembicCommands._answer(
            AlembicCommands._run_alembic(
                "upgrade", target, database_url=database_url
            ),
            empty="Migrations applied.",
            both_streams=True,
        )

    @staticmethod
    def downgrade(
        target: str = "-1", database_url: Optional[str] = None
    ) -> tuple[bool, str]:
        """Rollback migrations to target revision.

        Args:
            target: Revision to downgrade to.
            database_url: URL of the database to migrate.

        Returns:
            Tuple of (success, output).
        """
        return AlembicCommands._answer(
            AlembicCommands._run_alembic(
                "downgrade", target, database_url=database_url
            ),
            empty="Migrations rolled back.",
            both_streams=True,
        )

    @staticmethod
    def migrate(
        message: str, database_url: Optional[str] = None
    ) -> tuple[bool, str]:
        """Create new migration with auto-generated changes.

        Args:
            message: Revision message.
            database_url: URL of the database to compare the models against.

        Returns:
            Tuple of (success, output).
        """
        return AlembicCommands._answer(
            AlembicCommands._run_alembic(
                "revision", "--autogenerate", "-m", message,
                database_url=database_url,
            ),
            empty="Migration created.",
        )
