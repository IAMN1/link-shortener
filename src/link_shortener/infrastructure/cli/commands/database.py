from pathlib import Path
from link_shortener.application import RequestContext, SeedDatabaseUseCase
from link_shortener.infrastructure.database.models.base import Base
from link_shortener.infrastructure.database.manager import DatabaseManager
from link_shortener.infrastructure.database.role_loader import RoleLoader
from link_shortener.infrastructure.database.seed import seed_base_roles


def init_db(db_manager: DatabaseManager, use_alembic: bool) -> None:
    """
    Create all database tables based on SQLAlchemy models.
    This command is only allowed when USE_ALEMBIC is False.

    Args:
        db_manager: DatabaseManager instance.
        use_alembic: flag indicating whether the alembic is used or not
    """
    if use_alembic is True:
        raise RuntimeError(
            "USE_ALEMBIC is enabled. Please use 'alembic upgrade head' to manage schema."
        )
    db_manager.create_tables()
    print("Database tables created_successfully!")

def drop_db(db_manager: DatabaseManager, use_alembic: bool, confirm: bool = False) -> None:
    """
    Drop all database tables (destructive).
    This command is only allowed when USE_ALEMBIC is False.

    Args:
        db_manager: DatabaseManager instance.
        use_alembic: flag indicating whether the alembic is used or not
        confirm: Must be True to actually drop tables (safety flag).
    """
    if use_alembic is True:
        raise RuntimeError(
            "USE_ALEMBIC is enabled. Please use 'alembic downgrade base' to reset schema."
        )

    if not confirm:
        print("Use confirm=True to drop all tables.")
        return
    Base.metadata.drop_all(bind=db_manager.engine)
    print("All tables dropped successfully!")

def seed_db(use_case: SeedDatabaseUseCase, count: int, context: RequestContext) -> int:
    """
    Fill database with test links using SeedDatabaseUseCase.

    Args:
        use_case: SeedDatabaseUseCase instance.
        count: Number of test links to create.
        context: Request context.

    Returns:
        Number of successfully created links.
    """
    return use_case.execute(count, context)

def load_base_roles_from_cfg(db_manager: DatabaseManager) -> None:
    """
    Seed the database with default roles and permissions from the standard YAML config.
    This function is idempotent and safe to run multiple times.
    """
    with db_manager.session() as session:
        seed_base_roles(session)
    print("Roles and permissions seeded successfully.")

def load_custom_roles_from_cfg(
    db_manager: DatabaseManager, file_path: str, update_existing: bool = False
) -> None:
    """
    Load roles and permissions from a YAML file into the database.

    Args:
        db_manager: DatabaseManager instance.
        file_path: Path to the YAML file.
        update_existing: If True, update existing permissions/roles; otherwise only create new ones.
    """
    with db_manager.session() as session:
        loader = RoleLoader(session)
        loader.load_from_yaml(Path(file_path), update_existing=update_existing)
    action = "Updated" if update_existing else "Loaded"
    print(f"{action} roles and permission from {file_path}")
    

def check_db_connection(db_manager: DatabaseManager) -> bool:
    """
    Verify that the database is reachable.

    Args:
        db_manager: DatabaseManager instance.

    Returns:
        True if a simple SELECT 1 succeeds, False otherwise.
    """
    try:
        from sqlalchemy import text
        with db_manager.session() as session:
            result = session.execute(text("SELECT 1")).scalar()
            return result == 1
    except Exception:
        return False

def migrate_db(db_manager: DatabaseManager, use_alembic: bool) -> None:
    """
    Apply database migrations using Alembic.

    Args:
        db_manager: DatabaseManager instance.
        use_alembic: flag indicating whether alembic is enabled
    """
    if not use_alembic:
        print("Alembic is disabled. Use 'flask db init' to create tables.")
        return

    import subprocess
    import sys

    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            check=True
        )
        print("Migrations applied successfully.")
        if result.stdout:
            print(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Migration failed: {e.stderr}", file=sys.stderr)
        raise SystemExit(1)
