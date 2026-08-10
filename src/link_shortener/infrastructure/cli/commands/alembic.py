import os
import subprocess
import sys
from pathlib import Path
from typing import Optional


def _project_root() -> Path:
    """
    Locate the directory holding ``alembic.ini``.

    Alembic resolves ``script_location`` relative to the working directory,
    so without an explicit one the child inherits the operator's shell. That
    is not merely fragile -- running the command from ``src/`` failed with
    "No 'script_location' key found", and running it from a directory that
    happens to contain another ``alembic.ini`` executed *that* project's
    ``env.py``, with this process's environment handed to it.

    Two places are searched: upwards from this module, and upwards from the
    working directory. The first is what a source checkout answers with.
    The second is what an installed copy needs -- in the image the package
    is imported from ``site-packages``, so no parent of this file holds an
    ``alembic.ini``, and the fallback used to count levels up from here and
    land in ``/usr/local/lib/python3.12``. Alembic was then handed a
    directory with no configuration in it and died with "No 'script_location'
    key found", naming neither the directory nor the reason.

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

    HANDOFF_ENV_VAR = "ALEMBIC_DATABASE_URL"
    """Variable ``migrations/env.py`` reads the caller's database URL from.

    Alembic runs in a subprocess, and a subprocess inherits the ambient
    environment rather than the configuration of the application that
    launched it. Left to itself ``env.py`` rebuilt that configuration from
    scratch and could end up pointed at a different database than the caller
    -- under the ``testing`` profile, at a real one instead of the in-memory
    SQLite the profile pins on purpose.
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

        return subprocess.run(
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
    def status(database_url: Optional[str] = None) -> tuple[bool, str]:
        """Show current migration status.

        Args:
            database_url: URL of the database to report on.

        Returns:
            Tuple of (success, output). Alembic prints its own failures to
            stdout as well as stderr, so both are reported – otherwise a
            missing alembic.ini surfaced as an empty "Error: " line.
        """
        result = AlembicCommands._run_alembic("current", database_url=database_url)
        if result.returncode != 0:
            return False, f"Error: {result.stderr or result.stdout}".strip()
        return True, result.stdout or "No migrations applied."

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
        result = AlembicCommands._run_alembic(*args, database_url=database_url)
        if result.returncode != 0:
            return False, f"Error: {result.stderr or result.stdout}".strip()
        return True, result.stdout or "No migration history."

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
        result = AlembicCommands._run_alembic(
            "upgrade", target, database_url=database_url
        )
        if result.returncode != 0:
            return False, f"Error: {result.stderr}"
        # Alembic reports "Running upgrade X -> Y" on stderr, so on success
        # stdout is empty and this used to print a bare "Migrations applied."
        # -- identical output whether it created eight tables or did nothing
        # at all, and no way to tell which database it had been pointed at.
        return True, (result.stdout + result.stderr).strip() or "Migrations applied."

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
        result = AlembicCommands._run_alembic(
            "downgrade", target, database_url=database_url
        )
        if result.returncode != 0:
            return False, f"Error: {result.stderr}"
        # See `upgrade`: alembic's own account of what it did is on stderr.
        return True, (result.stdout + result.stderr).strip() or "Migrations rolled back."

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
        result = AlembicCommands._run_alembic(
            "revision", "--autogenerate", "-m", message, database_url=database_url
        )
        if result.returncode != 0:
            return False, f"Error: {result.stderr}"
        return True, result.stdout or "Migration created."

    @staticmethod
    def current(database_url: Optional[str] = None) -> tuple[bool, str]:
        """Show current revision.

        Args:
            database_url: URL of the database to report on.

        Returns:
            Tuple of (success, output).
        """
        result = AlembicCommands._run_alembic(
            "current", "--verbose", database_url=database_url
        )
        if result.returncode != 0:
            return False, f"Error: {result.stderr}"
        return True, result.stdout or "No current revision."
