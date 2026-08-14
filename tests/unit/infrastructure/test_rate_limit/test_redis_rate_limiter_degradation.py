"""Unit tests for RedisRateLimiter behaviour when Redis is unavailable."""

import time
from unittest.mock import Mock

import pytest
import redis

from link_shortener.infrastructure.rate_limit.redis_rate_limiter import (
    RedisRateLimiter,
)


@pytest.fixture()
def downed_limiter():
    """A limiter whose Redis refuses every command."""
    client = Mock()
    client.eval.side_effect = redis.ConnectionError("Connection refused")
    client.zremrangebyscore.side_effect = redis.ConnectionError("Connection refused")
    client.zcard.side_effect = redis.ConnectionError("Connection refused")
    return RedisRateLimiter(client, logger=Mock())


class TestFailsOpen:
    """A cache outage must not become an outage of the whole service."""

    def test_request_is_allowed_when_redis_is_down(self, downed_limiter):
        # This runs in before_request for every route, so raising here turned
        # a Redis outage into a 500 on every endpoint -- including the health
        # endpoints whose job is to report it.
        assert downed_limiter.is_allowed("client:1", limit=10, period=60) is True

    def test_remaining_reports_the_full_quota_when_redis_is_down(self, downed_limiter):
        assert downed_limiter.get_remaining("client:1", limit=10, period=60) == 10

    def test_outage_is_logged(self, downed_limiter):
        downed_limiter.is_allowed("client:1", limit=10, period=60)
        # Serving unthrottled is the lesser failure, but it must be visible.
        assert downed_limiter.logger.error.called


class TestNormalOperation:
    """The limiter still limits when Redis answers."""

    def test_allows_within_limit(self):
        client = Mock()
        client.eval.return_value = [1, 9]
        limiter = RedisRateLimiter(client, logger=Mock())
        assert limiter.is_allowed("client:1", limit=10, period=60) is True

    def test_blocks_over_limit(self):
        client = Mock()
        client.eval.return_value = [0, 0]
        limiter = RedisRateLimiter(client, logger=Mock())
        assert limiter.is_allowed("client:1", limit=10, period=60) is False


class TestOneRoundTripPerRequest:
    """
    The verdict and the remaining quota come from one call.

    Fetching them separately cost a second round trip on every allowed
    request, purely to fill in a response header -- and against a Redis that
    accepted TCP without answering, a second full socket timeout on every
    route.
    """

    def test_a_decision_costs_a_single_call(self):
        client = Mock()
        client.eval.return_value = [1, 7]
        limiter = RedisRateLimiter(client, logger=Mock())

        decision = limiter.check("client:1", limit=10, period=60)

        assert decision.allowed is True
        assert decision.remaining == 7
        assert client.eval.call_count == 1
        client.zcard.assert_not_called()


class TestOutageIsNotPaidPerRequest:
    """A limiter that cannot reach Redis must stop dialling it."""

    def test_redis_is_not_dialled_again_while_backing_off(self, downed_limiter):
        downed_limiter.retry_interval = 30

        for _ in range(5):
            downed_limiter.check("client:1", limit=10, period=60)

        # Otherwise every request pays a full socket timeout.
        assert downed_limiter.redis.eval.call_count == 1

    def test_requests_are_still_allowed_while_backing_off(self, downed_limiter):
        downed_limiter.retry_interval = 30

        for _ in range(3):
            assert downed_limiter.check("client:1", limit=10, period=60).allowed


class TestRefusalIsNotAnOutage:
    """
    A live server refusing a command is a misconfiguration, not a network
    failure -- and it is invisible everywhere else.

    ``PING`` succeeds on a read-only replica and under ``OOM``, so the cache
    reports healthy at exactly the moment the limiter cannot write.
    """

    @staticmethod
    def _refusing_limiter(error):
        """Build a limiter whose Redis answers with a refusal."""
        client = Mock()
        client.eval.side_effect = error
        return RedisRateLimiter(client, logger=Mock(), retry_interval=30)

    @pytest.mark.parametrize(
        "error",
        [
            redis.ResponseError("READONLY You can't write against a read only replica."),
            redis.ResponseError("OOM command not allowed when used memory > 'maxmemory'."),
            redis.AuthenticationError("WRONGPASS invalid username-password pair"),
        ],
    )
    def test_a_refusal_is_reported_as_not_enforcing(self, error):
        limiter = self._refusing_limiter(error)

        limiter.check("client:1", limit=10, period=60)

        # The request is still served -- but the fact that nothing is being
        # throttled must not be silent.
        assert limiter.is_enforcing() is False
        assert limiter.logger.error.called

    def test_a_refusal_does_not_stop_the_limiter_from_trying(self):
        # The connection is healthy; backing off from it would keep limits
        # switched off for longer than the misconfiguration lasts.
        limiter = self._refusing_limiter(redis.ResponseError("READONLY"))

        for _ in range(3):
            limiter.check("client:1", limit=10, period=60)

        assert limiter.redis.eval.call_count == 3

    def test_enforcement_resumes_once_the_server_accepts_writes(self):
        limiter = self._refusing_limiter(redis.ResponseError("READONLY"))
        limiter.check("client:1", limit=10, period=60)
        assert limiter.is_enforcing() is False

        limiter.redis.eval.side_effect = None
        limiter.redis.eval.return_value = [1, 9]
        limiter.check("client:1", limit=10, period=60)

        assert limiter.is_enforcing() is True


class TestAskingIsNotAnswering:
    """
    Reading the limiter's state must not change it.

    A back-off that clears itself inside the method that reports it makes
    asking "are limits being enforced?" declare the outage over, with
    nothing having checked whether Redis came back. The health check asks
    exactly that, and the endpoint it serves is exempt from the limiter, so
    it never reopened the outage by accident either.
    """

    @staticmethod
    def _downed(retry_interval=0):
        """A limiter whose Redis is down, back-off window already elapsed."""
        client = Mock()
        outage = redis.ConnectionError("Connection refused")
        client.eval.side_effect = outage
        client.ping.side_effect = outage
        return RedisRateLimiter(
            client, logger=Mock(), retry_interval=retry_interval
        )

    def test_asking_does_not_declare_the_outage_over(self):
        limiter = self._downed()
        limiter.check("client:1", limit=10, period=60)

        # Redis is still down. Every one of these must say so.
        assert [limiter.is_enforcing() for _ in range(3)] == [False, False, False]

    def test_a_quiet_service_keeps_reporting_the_outage(self):
        # The reproduction: Redis dies, one request notices, then silence
        # for longer than the retry interval. Nothing has verified recovery.
        limiter = self._downed()
        limiter.check("client:1", limit=10, period=60)

        assert limiter.is_enforcing() is False
        assert limiter.check("client:1", limit=10, period=60).allowed is True
        assert limiter.is_enforcing() is False

    def test_recovery_is_noticed_without_waiting_for_traffic(self):
        # The mirror mistake: a remembered outage that outlives the outage.
        limiter = self._downed()
        limiter.check("client:1", limit=10, period=60)
        assert limiter.is_enforcing() is False

        limiter.redis.ping.side_effect = None
        assert limiter.is_enforcing() is True


class TestOnlyOneCallerRetriesADeadRedis:
    """
    Every thread that arrives during an outage must not dial Redis itself.

    Each attempt costs a full socket timeout, so a service under load
    degrades on every request rather than on one per interval.
    """

    def test_concurrent_callers_do_not_each_pay_the_timeout(self):
        import threading

        client = Mock()
        outage = redis.ConnectionError("Connection refused")

        def slow_failure(*_args, **_kwargs):
            time.sleep(0.05)
            raise outage

        client.eval.side_effect = slow_failure
        limiter = RedisRateLimiter(client, logger=Mock(), retry_interval=30)

        # Prime the outage, then let a crowd arrive inside the window.
        limiter.check("client:1", limit=10, period=60)
        client.eval.reset_mock()

        threads = [
            threading.Thread(
                target=limiter.check, args=("client:1", 10, 60)
            )
            for _ in range(20)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert client.eval.call_count == 0


class TestEnforcementIsReportable:
    """Whether limits are on has to be answerable from outside."""

    def test_a_working_limiter_reports_enforcing(self):
        client = Mock()
        client.eval.return_value = [1, 9]
        limiter = RedisRateLimiter(client, logger=Mock())

        limiter.check("client:1", limit=10, period=60)

        assert limiter.is_enforcing() is True

    def test_an_unreachable_limiter_reports_not_enforcing(self, downed_limiter):
        downed_limiter.retry_interval = 30

        downed_limiter.check("client:1", limit=10, period=60)

        assert downed_limiter.is_enforcing() is False
