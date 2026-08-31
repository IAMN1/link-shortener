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
        database_schema: Whether the database the service is connected to
            actually holds this application's tables. Apart from
            ``database`` because the two failures look nothing alike and
            only one of them is a connection problem: a database that
            answers ``SELECT 1`` and holds no schema is reachable, healthy
            by every network measure, and answers ``500`` to the first
            real request. Measured -- a Docker stack whose migration ran
            against a different file reported ``healthy`` while its
            landing page answered ``500 no such table: roles``.
        cache: Whether the cache answered, or has nothing to answer with.
        cache_configured: Whether a cache backend is configured at all,
            which tells "the cache is fine" from "there is no cache".
        task_queue: Whether the queue can accept work.
        task_queue_configured: Whether there is a broker behind it at all,
            which tells "the workers are answering" from "the work is done
            in the request". The sibling of ``cache_configured``, and it
            was missing: on the arrangement that puts both in the process,
            ``/health`` answered ``"cache": "disabled"`` and
            ``"task_queue": "ok"`` for two dependencies in the same state.
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
    # Defaulted for the same reason ``rate_limiter`` is: the snapshot is
    # constructed in places that predate the field and have no database to
    # ask. The default is the optimistic one, which is safe here only
    # because the one implementation that serves ``/health`` always passes
    # a measured value -- a test asserting the endpoint's answer would
    # fail if it stopped.
    database_schema: bool = True
    # Defaulted true for the same reason, and true is the honest default
    # here: every construction that predates this field is a Celery-backed
    # one or a test that never asks.
    task_queue_configured: bool = True
    timed_out: Tuple[str, ...] = field(default=())

    @property
    def healthy(self) -> bool:
        """
        Whether every dependency that exists is answering.

        Here rather than at each surface, and that is the point of this
        object: the verdict was written twice, as a conjunction naming
        four fields in the CLI and as a check over the rendered strings in
        the endpoint. They agreed, and the fifth dependency would have had
        to be added to both in two unlike shapes -- with nothing failing
        if only one was.

        A cache nobody configured is not a broken cache: the documented
        local setup runs with ``REDIS_ENABLED=false``, and reporting that
        as a failure made a healthy install look broken.

        The schema is part of the verdict rather than a note beside it: an
        instance connected to a database without this application's tables
        serves nothing at all, and a verdict that called that healthy is
        the one this project measured itself giving.

        Returns:
            True when nothing is down.
        """
        return (
            self.database
            and self.database_schema
            and (self.cache or not self.cache_configured)
            and self.task_queue
            and self.rate_limiter
        )


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
    def check_schema(self) -> bool:
        """
        Verify that the database reached holds this application's tables.

        Separate from ``check_database`` on purpose. The two answer
        different questions and fail in ways that share no symptom: a
        connection that cannot be made raises out of the driver, while a
        connection to an empty database succeeds at everything until the
        first query against a table that is not there.

        Returns:
            ``True`` when every table the models declare is present.
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
