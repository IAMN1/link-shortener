import subprocess
import sys
from typing import Optional


class AlembicCommands:
    """Alembic migration management commands."""
    
    @staticmethod
    def _run_alembic(*args: str) -> subprocess.CompletedProcess:
        """Run alembic command and return result."""
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            capture_output=True,
            text=True
        )
    
    @staticmethod
    def status() -> str:
        """Show current migration status."""
        result = AlembicCommands._run_alembic("current")
        if result.returncode != 0:
            return f"Error: {result.stderr}"
        return result.stdout or "No migrations applied."
    
    @staticmethod
    def history(revision: Optional[str] = None) -> str:
        """Show migration history."""
        args = ["history"]
        if revision:
            args.extend(["-r", revision])
        result = AlembicCommands._run_alembic(*args)
        if result.returncode != 0:
            return f"Error: {result.stderr}"
        return result.stdout or "No migration history."
    
    @staticmethod
    def upgrade(target: str = "head") -> tuple[bool, str]:
        """Apply migrations to target revision."""
        result = AlembicCommands._run_alembic("upgrade", target)
        if result.returncode != 0:
            return False, f"Error: {result.stderr}"
        return True, result.stdout or "Migrations applied."
    
    @staticmethod
    def downgrade(target: str = "-1") -> tuple[bool, str]:
        """Rollback migrations to target revision."""
        result = AlembicCommands._run_alembic("downgrade", target)
        if result.returncode != 0:
            return False, f"Error: {result.stderr}"
        return True, result.stdout or "Migrations rolled back."
    
    @staticmethod
    def migrate(message: str) -> tuple[bool, str]:
        """Create new migration with auto-generated changes."""
        result = AlembicCommands._run_alembic("revision", "--autogenerate", "-m", message)
        if result.returncode != 0:
            return False, f"Error: {result.stderr}"
        return True, result.stdout or "Migration created."
    
    @staticmethod
    def current() -> tuple[bool, str]:
        """Show current revision."""
        result = AlembicCommands._run_alembic("current", "--verbose")
        if result.returncode != 0:
            return False, f"Error: {result.stderr}"
        return True, result.stdout or "No current revision."
