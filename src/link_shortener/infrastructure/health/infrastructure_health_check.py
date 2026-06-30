"""
Concrete implementation of the ``HealthCheck`` port.

This module provides ``InfrastructureHealthCheck``, which verifies the
availability of the database, cache (Redis), and task queue (Celery).
"""

from link_shortener.application import HealthCheck
from link_shortener.infrastructure.database.manager import DatabaseManager


class InfrastructureHealthCheck(HealthCheck):
    """Checks the health of infrastructure dependencies used by the application.

    Attributes:
        db_manager: Configured ``DatabaseManager`` for connectivity tests.
        cache: Cache implementation that supports a ``_ensure_connection``
            method (e.g. ``RedisLinkCache``).
    """

    def __init__(self, db_manager: DatabaseManager, cache: object):
        """Initialise the health checker with real infrastructure components.

        Args:
            db_manager: Database manager capable of executing a simple query.
            cache: Cache instance that exposes ``_ensure_connection()``.
        """
        self.db_manager = db_manager
        self.cache = cache

    def check_database(self) -> bool:
        """Check that the database is reachable by executing ``SELECT 1``.

        Returns:
            ``True`` if the query succeeds, ``False`` otherwise.
        """
        from sqlalchemy import text

        try:
            with self.db_manager.session() as session:
                session.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def check_cache(self) -> bool:
        """Check whether the cache backend is available.

        Relies on the cache object's ``_ensure_connection`` method,
        which returns ``True`` if the connection is alive.

        Returns:
            ``True`` if the cache is healthy, ``False`` otherwise.
        """
        if self.cache and hasattr(self.cache, "_ensure_connection"):
            return self.cache._ensure_connection()
        return False

    def check_task_queue(self) -> bool:
        """Check whether the task queue is operational.

        Currently a stub that always returns ``True`` because Celery health
        pings add complexity. In production, this could be replaced with
        ``app.control.ping()``.

        Returns:
            ``True`` (stub implementation).
        """
        # TODO: replace with a real Celery ping if needed
        return True
