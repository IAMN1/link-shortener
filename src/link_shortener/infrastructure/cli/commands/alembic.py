import os
# Alembic is run as a subprocess on purpose; see _run below.
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Optional

from link_shortener.infrastructure.configs.app import migration_url


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
                eight tables were created or nothing was.

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
        """Show current migration status.

        Args:
            database_url: URL of the database to report on.

        Returns:
            Tuple of (success, output).
        """
        return AlembicCommands._answer(
            AlembicCommands._run_alembic("current", database_url=database_url),
            empty="No migrations applied.",
        )

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
