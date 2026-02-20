from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from link_shortener.infrastructure.database.base import Base


class DatabaseManager:
    """
    Manages database connections and sessions.

    Provides a context manager for automatic session handling and a method
    to get a raw session for manual management.
    """

    def __init__(self, database_url: str, echo: bool = False):
        """
        Initialize the manager with database URL and optional echo flag.

        Args:
            database_url: SQLAlchemy database URL.
            echo: If True, log all SQL statements.
        """

        self.database_url = database_url
        self.echo = echo
        self.engine = None
        self._session_factory = None

    def connect(self) -> "DatabaseManager":
        """
        Establish connection to the database and create engine/session factory.

        Returns:
            Self for chaining.
        """

        self.engine = create_engine(
            self.database_url, pool_pre_ping=True, echo=self.echo
        )

        self._session_factory = sessionmaker(
            autocommit=False, autoflush=False, bind=self.engine
        )

        return self

    def close(self):
        """Dispose of the engine and close all connections."""
        if self.engine:
            self.engine.dispose()

    def create_tables(self):
        """
        Create all tables defined in models (for development/testing).

        Raises:
            RuntimeError: If database not connected.
        """
        if not self.engine:
            raise RuntimeError("Database not connected. Call connect() first.")
        Base.metadata.create_all(bind=self.engine)

    # ========== Варианты обращения к Базе Данных ==========

    ## Вариант 1 - через контекстный менеджер
    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        """
        Context manager that provides a database session.

        The session is automatically committed on success and rolled back on exception.
        The session is closed when exiting the context.

        Yields:
            SQLAlchemy Session object.
        """
        if not self._session_factory:
            raise RuntimeError("Database not initialized. Call connect() first.")

        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    ## Вариант 2 - через метод получения сесии
    def get_session(self) -> Session:
        """
        Obtain a database session without automatic commit/rollback.

        Warning: The caller is responsible for closing the session and handling transactions.

        Returns:
            SQLAlchemy Session object.
        """

        if not self._session_factory:
            raise RuntimeError("Database not initialized. Call connect() first.")

        return self._session_factory()
