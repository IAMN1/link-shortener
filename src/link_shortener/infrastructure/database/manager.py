from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from link_shortener.infrastructure.database.declarative_base import Base


class DatabaseManager:
    """
    Manages database connections and sessions.

    Provides a context manager for automatic session handling and a method
    to get a raw session for manual management.
    """

    def __init__(
        self, 
        database_url: str, 
        echo: bool, 
        database_type: str,
        **pool_params
    ):
        """
        nitialize the manager with database URL and optional echo flag.

        Args:
            database_url: SQLAlchemy database URL.
            echo: If True, log all SQL statements.
            database_type: Type of database ('sqlite' or 'postgresql').
            **pool_params: Additional parameters for connection pool (pool_size, max_overflow, etc.)
        """

        self.database_url = database_url
        self.echo = echo
        self.database_type = database_type
        self.pool_params = pool_params
        self.engine = None
        self._session_factory = None

    def connect(self) -> "DatabaseManager":
        """
        Establish connection to the database and create engine/session factory.

        Returns:
            Self for chaining.
        """

        engine_kwargs = {
            "echo": self.echo,
        }

        # Add pool parameters only for PostgreSQL (SQLite doesn't support them)
        if self.database_type == "postgresql":
            engine_kwargs.update(
                {
                    k: v for k, v in  self.pool_params.items() 
                        if v is not None and v != 0
                }
            )

        self.engine = create_engine(self.database_url, **engine_kwargs)

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
