from typing import Callable
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.infrastructure.database.manager import DatabaseManager
from link_shortener.infrastructure.database.unit_of_work import SQLAlchemyUnitOfWork


class DatabaseComponent:
    """
    Manages the lifecycle of the database connection and exposes a
    factory for ``UnitOfWork`` instances.

    The ``DatabaseManager`` is initialised lazily and remains alive for
    the lifetime of the application.
    """
    def __init__(self, database_url: str, echo: bool, db_type: str, pool_params: dict):
        """
        Args:
            database_url: SQLAlchemy connection URL.
            echo: If True, all SQL statements are logged.
            db_type: ``"sqlite"`` or ``"postgresql"``.
            pool_params: Dictionary of connection pool parameters
                (pool_size, max_overflow, pool_recycle, pool_pre_ping)
                forwarded to ``create_engine`` for PostgreSQL.
        """
        self.database_url = database_url
        self.echo = echo
        self.db_type = db_type
        self.pool_params = pool_params
        self._manager = None

    def get_db_manager(self) -> DatabaseManager:
        """
        Return the singleton ``DatabaseManager``.

        The manager is connected (engine and session factory created)
        on the first call.

        Returns:
            A fully initialised ``DatabaseManager``.
        """
        if self._manager is None:
            self._manager = DatabaseManager(
                database_url=self.database_url,
                echo=self.echo,
                database_type=self.db_type,
                **self.pool_params
            )
            self._manager.connect()
        return self._manager

    def get_uow_factory(self) -> Callable[[], UnitOfWork]:
        """
        Return a factory that creates a new ``UnitOfWork`` each time it is
        called.

        The factory accepts an optional ``read_only`` parameter that is
        forwarded to the ``SQLAlchemyUnitOfWork`` constructor.

        Returns:
            A callable with signature ``(read_only: bool = False) -> UnitOfWork``.
        """
        def factory(read_only: bool = False) -> UnitOfWork:
            return SQLAlchemyUnitOfWork(self.get_db_manager(), read_only=read_only)
        return factory

    def close(self):
        """Dispose of the database engine and all connections."""
        if self._manager:
            self._manager.close()
