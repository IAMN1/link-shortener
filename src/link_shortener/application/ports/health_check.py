from abc import ABC, abstractmethod


class HealthCheck(ABC):
    """
    Abstract health-check port for infrastructure components.
    """

    @abstractmethod
    def check_database(self) -> bool:
        """
        Verify that the database connection is alive.

        Returns:
            ``True`` if the database responds successfully, ``False`` otherwise.
        """
        ...

    @abstractmethod
    def check_cache(self) -> bool:
        """
        Verify that the cache backend (e.g. Redis) is reachable.

        Returns:
            ``True`` if the cache is available, ``False`` otherwise.
        """
        ...
    
    @abstractmethod
    def check_task_queue(self) -> bool:
        """
        Check whether the task queue (e.g. Celery) is operational.

        Returns:
            ``True`` if the task queue is healthy, ``False`` otherwise.
        """
        ...
