"""Unit tests for InfrastructureHealthCheck."""

import time
from contextlib import contextmanager
from unittest.mock import MagicMock, Mock, patch

import pytest
import redis

from link_shortener.domain import ShortCode
from link_shortener.infrastructure.cache.null_cache import NullCache
from link_shortener.infrastructure.cache.redis_cache import RedisLinkCache
from link_shortener.infrastructure.health.infrastructure_health_check import (
    InfrastructureHealthCheck,
)


def _db_manager(works=True):
    """
    Build a database manager whose connectivity probe succeeds or fails.

    Args:
        works: Whether the probe should succeed.

    Returns:
        A mock database manager.
    """
    manager = MagicMock()
    if not works:
        manager.probe.side_effect = RuntimeError("connection refused")
    return manager


class TestDatabase:
    """The database is the dependency the service cannot do without."""

    def test_reachable_database_is_healthy(self):
        check = InfrastructureHealthCheck(_db_manager(True), cache=None)
        assert check.check_database() is True

    def test_unreachable_database_is_unhealthy(self):
        check = InfrastructureHealthCheck(_db_manager(False), cache=None)
        assert check.check_database() is False


@contextmanager
def _redis_cache(client, retry_interval=0):
    """
    Provide a real ``RedisLinkCache`` over a stubbed Redis client.

    The mirrored defects below lived in how the health check read the
    cache's internal state, so a mocked cache cannot show them: it answers
    whatever the test told it to. The cache has to be the real one.

    The stub stays installed for the whole block, reconnections included --
    otherwise a cache that dropped its client dials a real localhost Redis
    and the test starts depending on whether one is running.

    Args:
        client: Stub standing in for the Redis client.
        retry_interval: Seconds before a dropped connection is retried.

    Yields:
        A connected ``RedisLinkCache``.
    """
    with patch("redis.from_url", return_value=client):
        yield RedisLinkCache(
            redis_url="redis://localhost:6379/0",
            prefix="test",
            logger=Mock(),
            link_ttl=60,
            stats_ttl=60,
            connect_timeout=1,
            socket_timeout=1,
            retry_interval=retry_interval,
            secret_key="unit-test-secret",
        )


class TestCache:
    """A cache that was switched off is not a failure."""

    def test_cache_without_a_connection_is_healthy(self):
        # NullCache / in-memory cache: nothing to connect to, so nothing can
        # be down. Reporting False made the panel claim Redis had failed on
        # a deployment that never wanted Redis.
        check = InfrastructureHealthCheck(_db_manager(), cache=NullCache())
        assert check.check_cache() is True
        # ...but "healthy" and "not there at all" must stay distinguishable.
        assert check.is_cache_configured() is False

    def test_missing_cache_is_healthy(self):
        check = InfrastructureHealthCheck(_db_manager(), cache=None)
        assert check.check_cache() is True

    def test_live_redis_is_healthy(self):
        client = Mock()
        client.ping.return_value = True
        with _redis_cache(client) as cache:
            check = InfrastructureHealthCheck(_db_manager(), cache=cache)
            assert check.check_cache() is True


class TestCacheStateIsNotInferred:
    """
    Both directions of the same mistake: reading a state instead of asking.

    The check used to ping the cache's client itself and, when that failed,
    fall back to the cache's own opinion. The ping told the cache nothing,
    so its "available" flag survived the outage -- and once some other
    request did notice and dropped the client, the missing client was read
    as "no cache configured".
    """

    def test_a_server_that_stopped_answering_is_reported_down(self):
        client = Mock()
        client.ping.return_value = True
        with _redis_cache(client) as cache:
            # Redis goes away after the cache connected successfully; nothing
            # else has touched it since, so its own flag still says
            # "available".
            client.ping.side_effect = redis.ConnectionError("connection refused")

            check = InfrastructureHealthCheck(_db_manager(), cache=cache)
            assert check.check_cache() is False

    def test_a_probe_leaves_the_cache_agreeing_with_it(self):
        client = Mock()
        client.ping.return_value = True
        with _redis_cache(client, retry_interval=3600) as cache:
            client.ping.side_effect = redis.ConnectionError("connection refused")

            InfrastructureHealthCheck(_db_manager(), cache=cache).check_cache()

            # A probe that reports an outage but leaves the cache believing
            # it is connected just moves the stale answer one caller along.
            assert cache._available is False

    def test_a_dropped_connection_is_not_mistaken_for_no_cache(self):
        client = Mock()
        client.ping.return_value = True
        with _redis_cache(client, retry_interval=3600) as cache:
            # An ordinary operation fails and the cache drops its client.
            client.get.side_effect = redis.ConnectionError("connection refused")
            cache.get_by_code(ShortCode("abc123"))
            assert cache._client is None

            check = InfrastructureHealthCheck(_db_manager(), cache=cache)
            # The deployment still runs with Redis: it is broken, not absent.
            assert check.is_cache_configured() is True
            assert check.check_cache() is False

    def test_a_recovered_server_is_reported_healthy_again(self):
        client = Mock()
        client.ping.return_value = True
        with _redis_cache(client) as cache:
            # Redis goes down: an ordinary operation fails, the cache drops
            # its client, and reconnecting fails too.
            outage = redis.ConnectionError("connection refused")
            client.get.side_effect = outage
            client.ping.side_effect = outage
            cache.get_by_code(ShortCode("abc123"))

            check = InfrastructureHealthCheck(_db_manager(), cache=cache)
            assert check.check_cache() is False

            # Redis comes back. Nothing else in the service has touched it,
            # so the health path itself has to notice.
            client.get.side_effect = None
            client.ping.side_effect = None
            assert check.check_cache() is True


class TestTheAnswerIsBounded:
    """
    A probe that answers late has not answered.

    The container healthcheck gives up after 10 seconds and counts the
    attempt as a failure, so an unbounded check gets a working service
    restarted rather than reporting on it.
    """

    def test_a_hanging_dependency_does_not_hold_the_answer_open(self):
        check = InfrastructureHealthCheck(
            _db_manager(), cache=NullCache(), task_queue=None, timeout=0.3
        )
        # A broker that accepts TCP and never answers: control.ping's own
        # timeout bounds waiting for replies, not connecting.
        check.check_task_queue = lambda: time.sleep(30)

        started = time.monotonic()
        state = check.snapshot()
        elapsed = time.monotonic() - started

        assert elapsed < 5
        assert state.task_queue is False
        assert state.timed_out == ("task_queue",)
        # The dependencies that did answer are still reported.
        assert state.database is True

    def test_the_budget_is_shared_not_granted_to_each_check(self):
        # Three checks each waiting the full budget in turn would take three
        # times the budget, which is not a budget.
        check = InfrastructureHealthCheck(
            _db_manager(), cache=NullCache(), task_queue=None, timeout=0.4
        )
        check.check_database = lambda: time.sleep(30)
        check.check_cache = lambda: time.sleep(30)
        check.check_task_queue = lambda: time.sleep(30)

        started = time.monotonic()
        state = check.snapshot()
        elapsed = time.monotonic() - started

        # Granting each check the full budget in turn would take three times
        # as long, so the margin has to be tighter than one extra check.
        assert elapsed < 0.9
        assert set(state.timed_out) == {"database", "cache", "task_queue"}

    def test_a_timeout_is_reported_apart_from_a_refusal(self):
        # Both mean "not usable", but only one names the hanging dependency.
        check = InfrastructureHealthCheck(
            _db_manager(works=False), cache=NullCache(), timeout=1.0
        )

        state = check.snapshot()

        assert state.database is False
        assert state.timed_out == ()


class TestDatabaseProbeIsIndependent:
    """The probe must not compete with the traffic it is measuring."""

    def test_the_probe_does_not_borrow_from_the_shared_pool(self):
        # Borrowing means a pool exhausted by real traffic is reported as a
        # database outage, after waiting out the pool timeout first.
        manager = _db_manager()
        check = InfrastructureHealthCheck(manager, cache=None)

        assert check.check_database() is True

        manager.probe.assert_called_once()
        manager.session.assert_not_called()


class TestTaskQueue:
    """A broker with no worker behind it is a silent failure worth reporting."""

    def test_queue_without_a_broker_is_healthy(self):
        # NullTaskQueue runs the work in-process.
        check = InfrastructureHealthCheck(
            _db_manager(), cache=None, task_queue=object()
        )
        assert check.check_task_queue() is True

    def test_celery_with_a_worker_is_healthy(self):
        queue = Mock()
        queue.celery_app.control.ping.return_value = [{"worker@host": {"ok": "pong"}}]
        check = InfrastructureHealthCheck(_db_manager(), cache=None, task_queue=queue)
        assert check.check_task_queue() is True

    def test_celery_without_a_worker_is_unhealthy(self):
        queue = Mock()
        queue.celery_app.control.ping.return_value = []
        check = InfrastructureHealthCheck(_db_manager(), cache=None, task_queue=queue)
        # Enqueued tasks would simply never run, and nothing else notices.
        assert check.check_task_queue() is False

    def test_unreachable_broker_is_unhealthy(self):
        queue = Mock()
        queue.celery_app.control.ping.side_effect = OSError("broker unreachable")
        check = InfrastructureHealthCheck(_db_manager(), cache=None, task_queue=queue)
        assert check.check_task_queue() is False
