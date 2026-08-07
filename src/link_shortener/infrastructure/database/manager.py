"""
Database connection and session manager.

Provides a context manager for automatic session handling and a factory
for manual sessions.
"""

from contextlib import contextmanager
from typing import Generator, Iterable

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

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
        connect_timeout: int = 0,
        statement_timeout: int = 0,
        **pool_params
    ):
        """
        Args:
            database_url: SQLAlchemy URL (e.g., ``sqlite:///...`` or
                ``postgresql+psycopg://...``).
            echo: If True, log every SQL statement.
            database_type: ``"sqlite"`` or ``"postgresql"``.
            connect_timeout: Seconds to wait for a PostgreSQL connection
                before giving up. ``0`` leaves it to the operating system,
                whose TCP timeout is measured in minutes -- on a network
                black hole a health check waited 75 seconds against a
                container probe that gives up after 10.
            statement_timeout: Seconds a single SQL statement may run before
                PostgreSQL aborts it. ``0`` disables the ceiling, and a
                query that never finishes then holds its worker forever.
            **pool_params: Extra keyword arguments forwarded to
                ``create_engine`` (pool_size, max_overflow, etc.). Only
                applied for PostgreSQL.
        """

        self.database_url = database_url
        self.echo = echo
        self.database_type = database_type
        self.connect_timeout = connect_timeout
        self.statement_timeout = statement_timeout
        self.pool_params = pool_params
        self.engine = None
        self._session_factory = None
        self._probe_engine = None

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
            engine_kwargs.update(self._connect_args())

        self.engine = create_engine(self.database_url, **engine_kwargs)

        if self.database_type == "sqlite":
            self._enforce_sqlite_foreign_keys(self.engine)

        self._session_factory = sessionmaker(
            autocommit=False, autoflush=False, bind=self.engine
        )

        return self

    @staticmethod
    def _enforce_sqlite_foreign_keys(engine) -> None:
        """
        Turn on foreign key enforcement for every SQLite connection.

        SQLite parses ``REFERENCES`` and then ignores it: enforcement is off
        unless each connection asks for it, and the pragma is per-connection,
        so it has to be set on connect rather than once. Off, an
        ``ON DELETE`` clause is decoration -- the cascade behind
        ``urls.owner_id`` simply did not happen, and deleting a user by hand
        left links pointing at an account that no longer exists.

        PostgreSQL needs nothing here; it has always enforced them.

        Args:
            engine: The engine whose connections need the pragma.
        """
        @event.listens_for(engine, "connect")
        def _set_pragma(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    def _connect_args(self) -> dict:
        """
        Build the driver-level connection arguments.

        Three different waits need bounding, and ``connect_timeout`` only
        covers the first of them:

        * establishing the connection -- ``connect_timeout``;
        * a query the server is running but not finishing (a lock, a slow
          plan) -- ``statement_timeout``, enforced server-side;
        * a peer that has gone away mid-query -- TCP keepalives, so the
          kernel gives up instead of waiting indefinitely on a socket that
          will never answer.

        Known gap, stated rather than papered over: none of these bound a
        server that is frozen but still reachable, because its kernel keeps
        acknowledging packets, so keepalives are answered and
        ``statement_timeout`` is never evaluated. Only an application-level
        deadline would cover that; it is recorded as an open item.

        Returns:
            ``connect_args`` for ``create_engine``, empty when nothing is
            configured.
        """
        args = {}

        if self.connect_timeout:
            args["connect_timeout"] = self.connect_timeout

        if self.statement_timeout:
            # libpq passes this through to the server as a session setting.
            args["options"] = f"-c statement_timeout={self.statement_timeout * 1000}"

            # Give up on a silent peer rather than block a worker forever.
            args["keepalives"] = 1
            args["keepalives_idle"] = 5
            args["keepalives_interval"] = 2
            args["keepalives_count"] = 3

        if not args:
            return {}

        return {"connect_args": args}

    def probe(self) -> None:
        """
        Verify connectivity on a connection of its own.

        Deliberately bypasses the shared pool. A health check that borrows
        from it reports "the database is down" when the pool is merely
        busy -- and does so after waiting out the pool timeout, which is
        both the wrong answer and a slow one. Under load that turns a
        saturated service into a restarted one.

        The probe engine holds nothing open between calls (``NullPool``),
        so it cannot itself become a leak on a path that runs every few
        seconds.

        Raises:
            Exception: Whatever the driver raises when it cannot connect.
        """
        if self._probe_engine is None:
            engine_kwargs = {"echo": False, "poolclass": NullPool}
            if self.database_type == "postgresql":
                engine_kwargs.update(self._connect_args())

            self._probe_engine = create_engine(self.database_url, **engine_kwargs)

        with self._probe_engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def close(self):
        """Dispose of the engine and all associated connections."""
        if self.engine:
            self.engine.dispose()
        if self._probe_engine:
            self._probe_engine.dispose()

    def create_tables(self):
        """
        Create all tables from models (development/testing only).

        Raises:
            RuntimeError: If connect() hasn't been called.
        """
        if not self.engine:
            raise RuntimeError("Database not connected. Call connect() first.")
        Base.metadata.create_all(bind=self.engine)

    def missing_tables(self, names: Iterable[str]) -> list[str]:
        """
        Report which of the named tables the database does not have.

        Lets a caller tell "the schema is not there yet" from "the database
        refused us", two states that otherwise arrive as the same exception
        out of the first query and get reported with the same alarm.

        Args:
            names: Table names to look for.

        Returns:
            The names that are absent, in the order given. Empty when all
            of them exist.

        Raises:
            RuntimeError: If connect() hasn't been called.
            Exception: Whatever the driver raises when it cannot connect.
        """
        if not self.engine:
            raise RuntimeError("Database not connected. Call connect() first.")

        inspector = inspect(self.engine)
        return [name for name in names if not inspector.has_table(name)]


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
