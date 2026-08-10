"""Handing a confirmation message to the queue, with and without a broker.

The click counter and the confirmation share a queue and must not share a
failure policy: a lost click is a counter nobody misses, a lost
confirmation is somebody who cannot finish registering. These are the
tests that keep the two apart.
"""

from unittest.mock import Mock, patch

import pytest

from link_shortener.application.context import RequestContext
from link_shortener.infrastructure.task_queue.celery_queue import CeleryTaskQueue
from link_shortener.infrastructure.task_queue.null_queue import NullTaskQueue


pytestmark = pytest.mark.usefixtures("detached_env")


def context():
    """A minimal request context."""
    return RequestContext(request_id="test")


class TestWithoutABroker:
    """``NullTaskQueue`` sends on the caller's thread and reports."""

    def test_it_sends_the_message(self):
        send = Mock()
        queue = NullTaskQueue(send_verification_fn=send)

        assert queue.enqueue_verification_email("u@e.com", "TOK", context()) is True
        send.assert_called_once_with("u@e.com", "TOK", context())

    def test_a_failure_is_reported_rather_than_swallowed(self):
        """The opposite of what the click counter does, deliberately."""
        send = Mock(side_effect=RuntimeError("smtp down"))
        queue = NullTaskQueue(send_verification_fn=send, logger=Mock())

        assert queue.enqueue_verification_email("u@e.com", "TOK", context()) is False

    def test_a_failure_is_logged(self):
        logger = Mock()
        queue = NullTaskQueue(
            send_verification_fn=Mock(side_effect=RuntimeError("smtp down")),
            logger=logger,
        )

        queue.enqueue_verification_email("u@e.com", "TOK", context())

        assert logger.error.called

    def test_the_token_is_not_logged(self):
        """It is a working credential until it is spent or expires."""
        logger = Mock()
        queue = NullTaskQueue(
            send_verification_fn=Mock(side_effect=RuntimeError("smtp down")),
            logger=logger,
        )

        queue.enqueue_verification_email("u@e.com", "SECRET-TOKEN", context())

        assert "SECRET-TOKEN" not in str(logger.mock_calls)

    def test_with_nothing_wired_it_says_so(self):
        """Silence here would be a registration that reports success and
        sends nothing at all."""
        queue = NullTaskQueue()

        assert queue.enqueue_verification_email("u@e.com", "TOK", context()) is False

    def test_a_click_still_fails_quietly(self):
        """The neighbouring method keeps its old policy: a redirect must
        not fail because a counter could not be updated."""
        queue = NullTaskQueue(update_fn=Mock(side_effect=RuntimeError("db down")))

        queue.enqueue_link_accessed("abc123", context())


class TestWithABroker:
    """``CeleryTaskQueue`` publishes and reports whether it managed to."""

    @pytest.fixture
    def task(self):
        """Replace the Celery task so no broker is involved."""
        with patch(
            "link_shortener.infrastructure.task_queue.tasks.send_verification_email"
        ) as task:
            yield task

    def test_it_publishes_the_task(self, task):
        queue = CeleryTaskQueue(logger=Mock())

        assert queue.enqueue_verification_email("u@e.com", "TOK", context()) is True

        email, token, ctx = task.delay.call_args.args
        assert email == "u@e.com"
        assert token == "TOK"
        assert ctx["request_id"] == "test"

    def test_a_broker_that_refuses_is_reported(self, task):
        task.delay.side_effect = RuntimeError("broker down")
        queue = CeleryTaskQueue(logger=Mock())

        assert queue.enqueue_verification_email("u@e.com", "TOK", context()) is False

    def test_the_token_is_not_logged(self, task):
        task.delay.side_effect = RuntimeError("broker down")
        logger = Mock()

        CeleryTaskQueue(logger=logger).enqueue_verification_email(
            "u@e.com", "SECRET-TOKEN", context()
        )

        assert "SECRET-TOKEN" not in str(logger.mock_calls)

    def test_a_recent_click_failure_does_not_hold_up_a_registration(self, task):
        """The back-off exists so a burst of redirects does not each pay
        the broker timeout. It decides by the clock, not by the request,
        and a registration skipped because some redirect failed a moment
        ago leaves a person with no way to confirm and no way to know
        why."""
        queue = CeleryTaskQueue(logger=Mock(), retry_interval=3600)
        with patch(
            "link_shortener.infrastructure.task_queue.tasks.process_link_accessed"
        ) as clicks:
            clicks.delay.side_effect = RuntimeError("broker down")
            queue.enqueue_link_accessed("abc123", context())

        assert queue.enqueue_verification_email("u@e.com", "TOK", context()) is True
        assert task.delay.called
