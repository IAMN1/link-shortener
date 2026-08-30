"""
Database connection and session manager.

Provides a context manager for automatic session handling and a factory
for manual sessions.
"""

from contextlib import contextmanager
from typing import Optional, Any, Dict, Generator, Iterable

from sqlalchemy.engine import Engine
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from link_shortener.infrastructure.database.models.base import Base


def postgresql_connect_args(
    connect_timeout: int = 0, statement_timeout: int = 0
) -> dict:
    """
    Build the driver-level connection arguments for PostgreSQL.

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

    A module-level function rather than a method because the migration
    environment needs the same arguments and has no manager to ask: it
    builds its own engine, and without these it waited on an unreachable
    server for over a minute where the application gave up in 3.6 seconds
    -- with the whole docker stack behind it, since ``app`` starts only
    once the migration has finished.

    Args:
        connect_timeout: Seconds to wait for a connection; ``0`` leaves it
            to the operating system.
        statement_timeout: Seconds a statement may run; ``0`` disables the
            ceiling.

    Returns:
        Mapping for ``create_engine(connect_args=...)``, empty when
        neither timeout is configured.
    """
    args: Dict[str, Any] = {}

    if connect_timeout:
        args["connect_timeout"] = connect_timeout

    if statement_timeout:
        # libpq passes this through to the server as a session setting.
        args["options"] = f"-c statement_timeout={statement_timeout * 1000}"

        # Give up on a silent peer rather than block a worker forever.
        args["keepalives"] = 1
        args["keepalives_idle"] = 5
        args["keepalives_interval"] = 2
        args["keepalives_count"] = 3

    return args


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
        # Annotated Optional rather than inferred from these assignments:
        # all three hold None until connect() runs.
        self.engine: Optional[Engine] = None
        self._session_factory: Optional[sessionmaker] = None
        self._probe_engine: Optional[Engine] = None

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
            # ``None`` is dropped and nothing else. Dropping a zero with
            # it would silently reverse two settings:
            # ``DATABASE_MAX_OVERFLOW=0`` caps the pool at ``pool_size``
            # and would arrive as SQLAlchemy's default of 10, and
            # ``DATABASE_POOL_RECYCLE=0`` would arrive as -1, which is
            # "never recycle". The zeros that mean "no pool" belong to the
            # other backends, and the whole block is skipped for them.
            engine_kwargs.update(
                {
                    k: v for k, v in self.pool_params.items()
                    if v is not None
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
        Build this manager's driver-level connection arguments.

        Returns:
            ``connect_args`` for ``create_engine``, empty when nothing is
            configured.
        """
        args = postgresql_connect_args(
            self.connect_timeout, self.statement_timeout
        )

        return {"connect_args": args} if args else {}

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

    def missing_declared_tables(self) -> list[str]:
        """
        Which of the tables the models declare the database does not have.

        This exists because "the database answered" and "the database holds
        this application's schema" are two questions, and only the first
        was ever asked. A stack whose migration ran somewhere else answers
        ``SELECT 1`` perfectly: the connection is real, the database is
        real, and it is empty. Measured on a fresh clone -- the migration
        container wrote a schema into its own filesystem, the application
        opened a different database, ``/health`` reported ``healthy`` and
        the landing page answered ``500 no such table: roles``.

        Asked of the shared engine, and **not** of the probe engine that
        ``probe`` uses, though the caller is the same health check. The
        question here is whether the connection this application serves
        from holds the schema, and a second engine is not that connection:
        against ``sqlite:///:memory:`` it is a different, empty database
        altogether, so the probe would report a missing schema for every
        such deployment -- including the entire test suite, which is how
        this was caught. The pool cost that ``probe`` avoids is paid once:
        the caller stops asking as soon as the answer is "nothing missing".

        The set is taken from ``Base.metadata`` rather than named here, so
        a model added later is covered without anybody remembering to add
        it. ``alembic_version`` is deliberately not among them: it is
        alembic's bookkeeping, not this application's schema, and a
        deployment whose tables were created some other way is not broken.

        Returns:
            The names that are absent, sorted. Empty when the schema is
            whole.

        Raises:
            RuntimeError: If connect() hasn't been called.
            Exception: Whatever the driver raises when it cannot connect.
                A database that cannot be reached is not a database with a
                missing schema, and the two are not merged here.
        """
        return self.missing_tables(sorted(Base.metadata.tables))

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
