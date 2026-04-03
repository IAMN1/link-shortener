from link_shortener.application import RequestContext, SeedDatabaseUseCase
from link_shortener.infrastructure.database.declarative_base import Base
from link_shortener.infrastructure.database.manager import DatabaseManager


def init_db(db_manager: DatabaseManager) -> None:
    """
    Create all database tables based on SQLAlchemy models.

    Args:
        db_manager: DatabaseManager instance.
    """
    db_manager.create_tables()
    print("Database tables created_successfully!")

def drop_db(db_manager: DatabaseManager, confirm: bool = False) -> None:
    """
    Drop all database tables (destructive).

    Args:
        db_manager: DatabaseManager instance.
        confirm: Must be True to actually drop tables (safety flag).
    """
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

def migrate_db(db_manager: DatabaseManager) -> None:
    """
    Placeholder for future Alembic migrations.

    Args:
        db_manager: DatabaseManager instance.
    
    TODO Реализовать
    """
    print("Database migrations not implemented yet. Use 'init' to create tables.")
