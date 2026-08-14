from link_shortener.infrastructure.database.manager import DatabaseManager


class DatabaseComponent:
    """
    Manages the lifecycle of the database connection.

    The ``DatabaseManager`` is initialised lazily and remains alive for
    the lifetime of the application.

    The unit of work is built by ``Container``, not here. This class used
    to offer a factory of its own, and it was a trap rather than a
    convenience: it passed no logger, so a repository warning about a row
    that is not normalised had nowhere to go, and nothing said so. No call
    site ever used it -- every one of them goes through
    ``Container.get_uow_factory``, which names the logger after the unit of
    work that owns it.
    """
    def __init__(
        self,
        database_url: str,
        echo: bool,
        db_type: str,
        pool_params: dict,
        connect_timeout: int = 0,
        statement_timeout: int = 0,
    ):
        """
        Args:
            database_url: SQLAlchemy connection URL.
            echo: If True, all SQL statements are logged.
            db_type: ``"sqlite"`` or ``"postgresql"``.
            pool_params: Dictionary of connection pool parameters
                (pool_size, max_overflow, pool_recycle, pool_pre_ping)
                forwarded to ``create_engine`` for PostgreSQL.
            connect_timeout: Seconds to wait for a PostgreSQL connection.
            statement_timeout: Seconds a single statement may run.
        """
        self.database_url = database_url
        self.echo = echo
        self.db_type = db_type
        self.pool_params = pool_params
        self.connect_timeout = connect_timeout
        self.statement_timeout = statement_timeout
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
                connect_timeout=self.connect_timeout,
                statement_timeout=self.statement_timeout,
                **self.pool_params
            )
            self._manager.connect()
        return self._manager

    def close(self):
        """Dispose of the database engine and all connections."""
        if self._manager:
            self._manager.close()
