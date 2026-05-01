"""
Database connection and session manager.

Provides a context manager for automatic session handling and a factory
for manual sessions.
"""

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from link_shortener.infrastructure.database.models.base import Base


class DatabaseManager:
    """
    Manages the database engine, session factory, and table creation.

    For PostgreSQL, connection pool parameters (pool_size, max_overflow,
    pool_recycle, pool_pre_ping) can be supplied via ``**pool_params``.
    """

    def __init__(
        self, 
        database_url: str, 
        echo: bool, 
        database_type: str,
        **pool_params
    ):
        """
        Args:
            database_url: SQLAlchemy URL (e.g., ``sqlite:///...`` or
                ``postgresql+psycopg://...``).
            echo: If True, log every SQL statement.
            database_type: ``"sqlite"`` or ``"postgresql"``.
            **pool_params: Extra keyword arguments forwarded to
                ``create_engine`` (pool_size, max_overflow, etc.). Only
                applied for PostgreSQL.
        """

        self.database_url = database_url
        self.echo = echo
        self.database_type = database_type
        self.pool_params = pool_params
        self.engine = None
        self._session_factory = None

    def connect(self) -> "DatabaseManager":
        """
        Create the SQLAlchemy engine and session factory.

        Pool parameters are injected into ``create_engine`` only when the
        database type is ``"postgresql"``. For SQLite they are ignored.

        Returns:
            Self for method chaining.
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
        """Dispose of the engine and all associated connections."""
        if self.engine:
            self.engine.dispose()

    def create_tables(self):
        """
        Create all tables from models (development/testing only).

        Raises:
            RuntimeError: If connect() hasn't been called.
        """
        if not self.engine:
            raise RuntimeError("Database not connected. Call connect() first.")
        Base.metadata.create_all(bind=self.engine)


    # ------------------------------------------------------------------
    # Session providers
    # ------------------------------------------------------------------

    ## Option 1 - via context manager
    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        """
        Context manager that provides a transactional session.

        The session is committed on success and rolled back on exception.
        The session is always closed when the block exits.

        Yields:
            A SQLAlchemy ``Session`` object.

        Raises:
            RuntimeError: If the manager has not been initialised.
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

    ## Option 2 - via the session retrieval method
    def get_session(self) -> Session:
        """
        Obtain a raw session **without** automatic transaction handling.

        The caller is responsible for committing, rolling back, and
        closing the session.

        Returns:
            A new SQLAlchemy ``Session``.

        Raises:
            RuntimeError: If the manager has not been initialised.
        """

        if not self._session_factory:
            raise RuntimeError("Database not initialized. Call connect() first.")

        return self._session_factory()
