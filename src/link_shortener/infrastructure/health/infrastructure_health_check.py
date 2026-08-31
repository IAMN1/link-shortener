"""
Concrete implementation of the ``HealthCheck`` port.

This module provides ``InfrastructureHealthCheck``, which asks the
database, the cache, the queue and the throttle whether they are answering.
Not the log: the chains that write it report themselves, through
``LoggingStatusPort``, because a probe cannot tell a journal nobody is
writing from one nobody has anything to write to.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Callable, Optional

from link_shortener.application import (
    CacheHealth, HealthCheck, RateLimiter, TaskQueue,
)
from link_shortener.application.ports.health_check import HealthSnapshot
from link_shortener.infrastructure.database.manager import DatabaseManager


class _Deadline:
    """
    A shared time budget handed out to successive waits.

    Waiting the full budget on each component in turn would multiply it by
    the number of components, which is not a budget.

    Attributes:
        expires_at: Monotonic timestamp at which nothing more may be waited
            for.
    """

    def __init__(self, seconds: float):
        """
        Args:
            seconds: Total time available.
        """
        self.expires_at = time.monotonic() + seconds

    def remaining(self) -> float:
        """
        Return the time still available, never negative.

        Returns:
            Seconds left in the budget.
        """
        return max(0.0, self.expires_at - time.monotonic())


class InfrastructureHealthCheck(HealthCheck):
    """Checks the health of infrastructure dependencies used by the application.

    A dependency that was deliberately switched off is reported healthy: the
    question a health check answers is "is anything broken", and an absent
    optional component is not.

    Every observation is taken through ``snapshot()``, under one shared time
    budget. Each individual check also carries its own deadline, but those
    only bound the failures anyone anticipated; the budget bounds the
    answer itself, which is what the caller actually depends on.

    Attributes:
        db_manager: Configured ``DatabaseManager`` for connectivity tests.
        cache: Cache implementing ``CacheHealth`` (e.g. ``RedisLinkCache``).
        task_queue: Task queue implementation, if one is configured.
        timeout: Total seconds a snapshot may take.
        rate_limiter: Rate limiter, if one is configured.
    """

    PING_TIMEOUT_SECONDS = 1.0
    """How long to wait for a Celery worker to answer before calling it down."""

    CACHE_TTL_SECONDS = 2.0
    """How long one observation stands in for the next.

    ``/health`` is anonymous and exempt from throttling -- rightly, a
    probe has to answer when everything else is refusing -- so without a
    snapshot every request costs a query, a Redis ping, a broker ping and
    a pool of four OS threads. Two seconds is short against any
    orchestrator's probe interval and long enough that a flood costs one
    observation rather than one each.
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        cache: Optional[CacheHealth],
        task_queue: Optional[TaskQueue] = None,
        timeout: float = 5.0,
        rate_limiter: Optional[RateLimiter] = None,
        clock: Optional[Callable[[], float]] = None,
    ):
        """Initialise the health checker with real infrastructure components.

        Args:
            db_manager: Database manager capable of executing a simple query.
            cache: Cache instance implementing the ``CacheHealth`` port.
            task_queue: Task queue implementation, used to tell a broker that
                is down from one that was never configured.
            timeout: Total seconds ``snapshot()`` may spend.
            rate_limiter: Rate limiter, asked whether it is still enforcing.
        """
        self.db_manager = db_manager
        self.cache = cache
        self.task_queue = task_queue
        self.timeout = timeout
        self.rate_limiter = rate_limiter
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._cached: Optional[HealthSnapshot] = None
        self._cached_at = 0.0
        # Set once the schema has been seen whole; see ``check_schema``
        # for why this one answer is remembered while the others are
        # re-asked. A plain attribute rather than a guarded one: the
        # observation runs under ``_lock``, and the only write is False
        # to True.
        self._schema_seen = False

    def snapshot(self) -> HealthSnapshot:
        """
        Answer from the last observation while it is still fresh.

        The observation itself is taken by ``_observe``; this is only the
        gate in front of it. The lock is held across the observation on
        purpose: without it a burst of requests arriving on an empty cache
        each starts its own pool, which is the case that hurt.

        A monotonic clock, because a wall clock stepping backwards -- NTP,
        a container resuming -- would freeze the answer for as long as the
        step.

        Returns:
            The state of all dependencies, at most ``CACHE_TTL_SECONDS``
            old.
        """
        with self._lock:
            if (
                self._cached is not None
                and self._clock() - self._cached_at < self.CACHE_TTL_SECONDS
            ):
                return self._cached

            self._cached = self._observe()
            # Stamped after the observation, not before it. Stamped before,
            # an observation slower than the TTL is already stale when it
            # is stored, so the next caller waiting on this lock observes
            # again -- and the lock turns a slow dependency into a queue.
            # With a 2.5 s probe against a 2 s TTL: five parallel
            # requests took 12.52 s instead of 2.51 s, and the cost grows
            # with the number of callers, on an endpoint that is anonymous
            # and exempt from throttling.
            self._cached_at = self._clock()
            return self._cached

    def _observe(self) -> HealthSnapshot:
        """Observe every dependency at once, within the configured budget.

        The checks run concurrently, so the cost is the slowest dependency
        rather than their sum, and a dependency that never answers costs the
        budget rather than the whole response. Run in sequence and bounded
        only by their own timeouts, a black-holed broker held ``/health``
        open indefinitely while the container probe timed out every 30
        seconds and eventually restarted a working service.

        A component still running when the budget expires is reported
        unhealthy and named in ``timed_out``. Its thread is left to finish
        on its own: there is no way to cancel a socket read mid-flight, and
        waiting for one to notice would give back the unbounded wait this
        exists to prevent.

        Returns:
            The state of all dependencies.
        """
        checks = {
            "database": self.check_database,
            "cache": self.check_cache,
            "task_queue": self.check_task_queue,
            "rate_limiter": self.check_rate_limiter,
        }

        # The schema is asked on this thread rather than in the pool
        # below, and the reason is a trap this project has already written
        # up: under ``SingletonThreadPool`` an in-memory SQLite database
        # hands every thread its own -- so the worker inspects a database
        # nobody migrated and every such deployment reports a missing
        # schema. Measured: it reddened the CLI, integration and e2e
        # suites at once, all of which run on ``sqlite:///:memory:``.
        #
        # What that costs, said plainly: this call is outside the budget,
        # so a database that hangs rather than refusing holds ``/health``
        # open for as long as it hangs.
        #
        # The memo inside ``check_schema`` bounds that, but only on the
        # happy path -- it latches on success, and a missing schema is
        # deliberately asked about again so that a database migrated
        # while the service runs is noticed. So in the one fault this
        # check exists to find, the unbounded call is not spent once at
        # start-up: it is spent on every observation, for as long as the
        # schema is missing. Measured with a 2 s stub against a 0.5 s
        # budget: 2.01 s on the first call and 2.01 s on the next two,
        # where a whole schema costs 2.01 s once and 0.00 s afterwards.
        # An observation is taken at most once per ``CACHE_TTL_SECONDS``
        # and runs under ``_lock``, so that is the period of the cost,
        # not its duration.
        #
        # Accepted rather than overlooked, and the trade is with the
        # alternative: inside the pool the in-memory case has no answer
        # at all, and a probe that is wrong about every SQLite deployment
        # is worse than one that can be slow while a deployment is
        # unmigrated -- a state in which the service serves nothing
        # anyway, and whose remedy this row is what tells an operator.
        schema_whole = self.check_schema()

        # Not a context manager: its __exit__ joins the worker threads, and a
        # check that is hanging would hold the response open there instead.
        executor = ThreadPoolExecutor(max_workers=len(checks))
        try:
            futures = {
                name: executor.submit(check) for name, check in checks.items()
            }

            results = {}
            timed_out = []
            deadline = _Deadline(self.timeout)

            for name, future in futures.items():
                try:
                    results[name] = bool(future.result(timeout=deadline.remaining()))
                except FutureTimeout:
                    results[name] = False
                    timed_out.append(name)
                except Exception:
                    results[name] = False
        finally:
            executor.shutdown(wait=False)

        return HealthSnapshot(
            database=results["database"],
            database_schema=schema_whole,
            cache=results["cache"],
            cache_configured=self.is_cache_configured(),
            task_queue=results["task_queue"],
            rate_limiter=results["rate_limiter"],
            timed_out=tuple(timed_out),
        )

    def check_rate_limiter(self) -> bool:
        """Check whether request limits are actually being enforced.

        The limiter fails open, so an outage costs no requests -- it costs
        the limits themselves, silently. ``PING`` succeeds on a read-only
        replica and under ``OOM``, which is exactly when the limiter cannot
        write, so the cache's state does not answer this question.

        Returns:
            ``True`` if limits are in force, or no limiter is configured.
        """
        if self.rate_limiter is None:
            return True

        try:
            return bool(self.rate_limiter.is_enforcing())
        except Exception:
            return False

    def check_database(self) -> bool:
        """Check that the database is reachable by executing ``SELECT 1``.

        Uses a connection of the probe's own rather than the shared pool, so
        that a pool exhausted by real traffic is not reported as a database
        outage after waiting out the pool timeout.

        Returns:
            ``True`` if the query succeeds, ``False`` otherwise.
        """
        try:
            self.db_manager.probe()
            return True
        except Exception:
            return False

    def check_schema(self) -> bool:
        """Check that the database reached holds this application's tables.

        A database that cannot be reached at all reports ``False`` here
        too, and that is not a second alarm for one fault -- ``database``
        is already ``False`` beside it, and the pair reads "cannot
        connect", while ``database`` true and this one false reads
        "connected to the wrong database, or the migration never ran".

        Asked until it succeeds once, then remembered. Unlike every other
        check here, this one asks a question whose answer does not come
        back: a schema does not un-migrate itself, and the fault being
        guarded against -- a migration that ran against a different
        database -- is fixed by a deployment rather than by waiting. A
        table dropped by hand afterwards shows up in the error journal on
        the request that needed it, which is where an operator would look
        for it; what must not happen is this probe holding a pool
        connection every thirty seconds forever to re-confirm something
        settled at start-up.

        Returns:
            ``True`` when every table the models declare is present.
        """
        if self._schema_seen:
            return True

        try:
            whole = not self.db_manager.missing_declared_tables()
        except Exception:
            return False

        self._schema_seen = whole
        return whole

    def check_cache(self) -> bool:
        """Check whether the cache backend is available.

        The cache is asked to probe itself. Working it out from the outside
        got the answer wrong in both directions: a direct ``ping`` on the
        cache's client never told the cache anything, so its "available"
        flag survived the outage and a switched-off Redis was reported as
        healthy; and once some other request did drop the client, its
        absence read as "no cache configured", so a recovered Redis stayed
        "disabled" indefinitely.

        A cache with no connection to make -- the in-memory or null
        implementations, chosen when caching is switched off -- is reported
        healthy. It cannot be down, and calling it unhealthy made the status
        panel claim Redis had failed on a deployment that never asked for
        Redis in the first place.

        Returns:
            ``True`` if the cache is healthy or has nothing to connect to.
        """
        # ``is_cache_configured`` already answers False for an absent cache,
        # but it says so through a method call, and the absence has to be
        # written out here for the attribute to read as a cache below.
        if self.cache is None or not self.is_cache_configured():
            return True

        try:
            return bool(self.cache.ping())
        except Exception:
            return False

    def is_cache_configured(self) -> bool:
        """
        Report whether a cache with a real connection is in use.

        Lets callers tell "the cache is fine" from "there is no cache",
        which a bare boolean cannot express. The question is about the
        deployment, so the answer is the cache's own and does not move when
        the server does.

        Returns:
            ``True`` if the cache talks to a server.
        """
        return bool(self.cache and self.cache.is_configured())

    def check_task_queue(self) -> bool:
        """Check whether the task queue is operational.

        A queue that runs tasks in-process has no broker to lose and is
        always healthy. A Celery-backed one is asked for a live worker with
        ``control.ping()``: without a worker the tasks are silently never
        run, which is exactly what a health check exists to surface.

        ``limit=1`` because one live worker is the whole question. The
        call is a broadcast, and without a limit it goes on collecting
        replies until the timeout expires however quickly the first one
        arrives -- measured in the container, 1.027 s against 0.004 s for
        the same verdict, on every observation that missed the cache. With
        no worker at all both forms wait out the timeout and return
        nothing, so the failure is detected exactly as before.

        Returns:
            ``True`` if the queue can accept work.
        """
        if self.task_queue is None:
            return True

        celery_app = getattr(self.task_queue, "celery_app", None)
        if celery_app is None:
            # Null or synchronous queue: nothing to be unavailable.
            return True

        try:
            replies = celery_app.control.ping(
                timeout=self.PING_TIMEOUT_SECONDS, limit=1
            )
            return bool(replies)
        except Exception:
            return False
