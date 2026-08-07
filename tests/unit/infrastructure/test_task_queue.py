from unittest.mock import Mock, patch

import pytest

from link_shortener.application.context import RequestContext
from link_shortener.infrastructure.configs.celery.celery_config import CeleryConfig
from link_shortener.infrastructure.task_queue.celery_queue import CeleryTaskQueue
from link_shortener.infrastructure.task_queue.null_queue import NullTaskQueue


# Patching the Celery task imports `task_queue.tasks`, which finalises the
# Celery application, and `LinkShortenerCelery.on_configure` builds a real
# configuration profile at that moment. The profile reads `.env`, so without
# this the module answers to the developer's file: a single bad line there
# turned this into a fixture error while the code under test was untouched.
pytestmark = pytest.mark.usefixtures("detached_env")


class TestNullTaskQueue:
    """Tests for NullTaskQueue synchronous fallback."""

    def test_no_op_when_no_update_fn(self):
        q = NullTaskQueue()
        ctx = RequestContext(request_id="test")
        q.enqueue_link_accessed("abc123", ctx)

    def test_calls_update_fn_synchronously(self):
        fn = Mock()
        q = NullTaskQueue(update_fn=fn)
        ctx = RequestContext(request_id="test")
        q.enqueue_link_accessed("abc123", ctx)
        fn.assert_called_once_with("abc123", ctx)

    def test_swallows_exceptions_from_update_fn(self):
        fn = Mock(side_effect=RuntimeError("db down"))
        q = NullTaskQueue(update_fn=fn)
        ctx = RequestContext(request_id="test")
        q.enqueue_link_accessed("abc123", ctx)

    def test_set_update_fn(self):
        q = NullTaskQueue()
        fn = Mock()
        q.set_update_fn(fn)
        ctx = RequestContext(request_id="test")
        q.enqueue_link_accessed("xyz789", ctx)
        fn.assert_called_once_with("xyz789", ctx)


@pytest.fixture
def dispatch():
    """Replace the Celery task so no broker is involved."""
    with patch(
        "link_shortener.infrastructure.task_queue.tasks.process_link_accessed"
    ) as task:
        yield task


def _context():
    """A minimal request context for enqueueing."""
    return RequestContext(request_id="test")


class TestBrokerOutageIsNotPaidTwice:
    """
    An unreachable broker must cost one bounded attempt, not one per request.

    Enqueueing runs inside the redirect handler, so every second spent
    waiting on the broker is a second the client waits for a 302.
    """

    def test_failed_publish_does_not_reach_the_caller(self, dispatch):
        dispatch.delay.side_effect = OSError("broker unreachable")
        queue = CeleryTaskQueue(logger=Mock())

        queue.enqueue_link_accessed("abc123", _context())

    def test_broker_is_not_dialled_again_while_backing_off(self, dispatch):
        dispatch.delay.side_effect = OSError("broker unreachable")
        queue = CeleryTaskQueue(logger=Mock(), retry_interval=30)

        for _ in range(5):
            queue.enqueue_link_accessed("abc123", _context())

        # Only the first request pays for the broker being down.
        assert dispatch.delay.call_count == 1

    def test_dispatching_resumes_once_the_interval_has_passed(self, dispatch):
        dispatch.delay.side_effect = OSError("broker unreachable")
        queue = CeleryTaskQueue(logger=Mock(), retry_interval=30)

        with patch(
            "link_shortener.infrastructure.task_queue.celery_queue.time.monotonic",
            return_value=1000.0,
        ):
            queue.enqueue_link_accessed("abc123", _context())
            queue.enqueue_link_accessed("abc123", _context())

        assert dispatch.delay.call_count == 1

        with patch(
            "link_shortener.infrastructure.task_queue.celery_queue.time.monotonic",
            return_value=1031.0,
        ):
            queue.enqueue_link_accessed("abc123", _context())

        assert dispatch.delay.call_count == 2

    def test_a_working_broker_is_never_skipped(self, dispatch):
        queue = CeleryTaskQueue(logger=Mock(), retry_interval=30)

        for _ in range(5):
            queue.enqueue_link_accessed("abc123", _context())

        assert dispatch.delay.call_count == 5


class TestPublishingBounds:
    """The broker connection carries an explicit deadline."""

    def test_socket_bounds_are_set_for_the_broker(self):
        options = CeleryConfig.broker_transport_options

        assert options["socket_connect_timeout"] == (
            CeleryConfig.broker_connection_timeout
        )
        assert options["socket_timeout"] == CeleryConfig.broker_connection_timeout
        assert options["retry_on_timeout"] is False

    def test_the_deadline_is_short_enough_for_a_request(self):
        # The redirect handler waits for this. Anything approaching the
        # container healthcheck timeout (10s) is not a bound.
        assert 0 < CeleryConfig.broker_connection_timeout <= 5

    def test_publishing_is_not_retried(self):
        # Retrying spends the caller's request on a broker already known to
        # be unreachable.
        assert CeleryConfig.task_publish_retry is False

    def test_the_connection_is_attempted_once(self):
        # ensure_connection's back-off (2s, 4s, 6s, 8s) is what a refused
        # broker actually costs; the socket timeouts do not cap it.
        assert CeleryConfig.broker_transport_options["max_retries"] == 0

    def test_no_result_is_announced_to_a_store_nobody_reads(self):
        # send_task tells the result store about the task before publishing
        # it. Nothing reads a result back, and with the store unreachable
        # that announcement cost the redirect 19.5 seconds.
        assert CeleryConfig.task_ignore_result is True

    def test_the_result_store_cannot_stall_a_request(self):
        # Its default policy is 20 retries a second apart.
        policy = CeleryConfig.result_backend_transport_options["retry_policy"]
        assert policy["max_retries"] == 0


class TestOnlyOneCallerRetriesTheBroker:
    """A burst during a broker outage must cost one attempt, not one each."""

    def test_concurrent_callers_do_not_each_pay_the_timeout(self, dispatch):
        import threading
        import time as _time

        def slow_failure(*_args, **_kwargs):
            _time.sleep(0.05)
            raise OSError("broker unreachable")


        dispatch.delay.side_effect = slow_failure
        # A short window, so the crowd arrives at the moment it reopens --
        # inside the window everyone is turned away regardless, so that
        # would not exercise the race at all.
        queue = CeleryTaskQueue(logger=Mock(), retry_interval=0.2)

        queue.enqueue_link_accessed("abc123", _context())
        dispatch.delay.reset_mock()
        _time.sleep(0.25)

        threads = [
            threading.Thread(
                target=queue.enqueue_link_accessed, args=("abc123", _context())
            )
            for _ in range(20)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # Exactly one caller finds out whether the broker came back.
        assert dispatch.delay.call_count == 1
