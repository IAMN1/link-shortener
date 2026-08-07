from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Tuple


@dataclass(frozen=True)
class HealthSnapshot:
    """
    The state of every dependency, taken as one bounded observation.

    Exists so that every surface reporting health reports the *same* health.
    Callers that asked each component separately drifted apart from each
    other, and had no way to stop a single unresponsive dependency from
    holding the whole answer open.

    Attributes:
        database: Whether the database answered.
        cache: Whether the cache answered, or has nothing to answer with.
        cache_configured: Whether a cache backend is configured at all,
            which tells "the cache is fine" from "there is no cache".
        task_queue: Whether the queue can accept work.
        rate_limiter: Whether request limits are actually being enforced. A
            limiter that cannot reach its backend lets everything through,
            brute-force protection on the auth endpoints included, and
            nothing else in the system would show it.
        timed_out: Names of the components that did not answer within the
            budget. They are reported unhealthy, but the distinction matters:
            "did not answer in time" is not the same finding as "answered
            no", and a probe that quietly reports the two alike hides which
            dependency is hanging.
    """

    database: bool
    cache: bool
    cache_configured: bool
    task_queue: bool
    rate_limiter: bool = True
    timed_out: Tuple[str, ...] = field(default=())


class HealthCheck(ABC):
    """
    Abstract health-check port for infrastructure components.
    """

    @abstractmethod
    def snapshot(self) -> HealthSnapshot:
        """
        Observe every dependency at once, within a fixed time budget.

        Implementations must return within that budget whatever the
        dependencies do, because the caller is a liveness probe: an answer
        that arrives after the orchestrator's timeout is indistinguishable
        from no answer, and gets the container restarted.

        Returns:
            The state of all dependencies.
        """
        ...

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
