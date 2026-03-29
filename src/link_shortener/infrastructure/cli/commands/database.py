from link_shortener.domain.entities.link import Link
from link_shortener.domain.value_objects.original_url import OriginalUrl
from link_shortener.infrastructure.database.declarative_base import Base
from link_shortener.infrastructure.database.manager import DatabaseManager


def init_db(db_manager: DatabaseManager) -> None:
    """Create all database tables based on SQLAlchemy models."""
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

def seed_db(repository, policy, count: int = 10) -> int:
    """
    Fill the database with test links.

    Generates unique URLs of the form https://seed-db.com/0, 1, 2, ...

    Args:
        repository: LinkRepository instance.
        policy: ShorteningPolicy for hash and code generation.
        count: Number of test links to create.

    Returns:
        Number of successfully created links.
    """
    created = 0
    for i in range(count):
        # Генерируем уникальный URL с номером итерации
        url = f"https://seed-db.com/{i}"
        try:
            original_url = OriginalUrl(url)
            url_hash = policy.calculate_hash(original_url)
            short_code = policy.generate_code_for_url(original_url)

            link = Link.create(
                url_hash=url_hash,
                short_code=short_code,
                original_url=original_url,
            )
            repository.save(link)
            created += 1
        except Exception as e:
            print(f"⚠️ Failed to create link for {url}: {e}")
    return created

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
    TODO Реализовать
    """
    print("Database migrations not implemented yet. Use 'init' to create tables.")