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


class TestTheAccountExistsNoticeWithoutABroker:
    """The notice follows the confirmation's policy, not the counter's.

    It is the message a registration on a taken address produces, and it
    is what keeps that path the same length as the free one: without a
    broker the hand-off *is* the SMTP exchange. So a failure has to be
    reported and recorded rather than swallowed -- swallowed, nobody finds
    out that half the registrations stopped costing what the other half
    costs.
    """

    def test_it_sends_the_message(self):
        send = Mock()
        queue = NullTaskQueue(send_account_exists_fn=send)

        assert queue.enqueue_account_exists_email("u@e.com", context()) is True
        send.assert_called_once_with("u@e.com", context())

    def test_a_failure_is_reported_rather_than_swallowed(self):
        """The neighbouring ``enqueue_link_accessed`` swallows on purpose,
        and copying that policy here would report a lost message as sent."""
        send = Mock(side_effect=RuntimeError("smtp down"))
        queue = NullTaskQueue(send_account_exists_fn=send, logger=Mock())

        assert queue.enqueue_account_exists_email("u@e.com", context()) is False

    def test_a_failure_is_logged(self):
        logger = Mock()
        queue = NullTaskQueue(
            send_account_exists_fn=Mock(side_effect=RuntimeError("smtp down")),
            logger=logger,
        )

        queue.enqueue_account_exists_email("u@e.com", context())

        assert logger.error.called

    def test_with_nothing_wired_it_says_so(self):
        """What the container's wiring line is for. Unwired, the taken
        path sends nothing while the free path still submits a message,
        and the timing channel reopens with every answer still identical."""
        queue = NullTaskQueue()

        assert queue.enqueue_account_exists_email("u@e.com", context()) is False


class TestTheAccountExistsNoticeWithABroker:
    """Publishing it, and the back-off it must not consult."""

    @pytest.fixture
    def task(self):
        """Replace the Celery task so no broker is involved."""
        with patch(
            "link_shortener.infrastructure.task_queue.tasks."
            "send_account_exists_email"
        ) as task:
            yield task

    def test_it_publishes_the_task(self, task):
        queue = CeleryTaskQueue(logger=Mock())

        assert queue.enqueue_account_exists_email("u@e.com", context()) is True

        email, ctx = task.delay.call_args.args
        assert email == "u@e.com"
        assert ctx["request_id"] == "test"

    def test_a_broker_that_refuses_is_reported(self, task):
        task.delay.side_effect = RuntimeError("broker down")
        queue = CeleryTaskQueue(logger=Mock())

        assert queue.enqueue_account_exists_email("u@e.com", context()) is False

    def test_a_recent_click_failure_does_not_hold_up_the_notice(self, task):
        """Same rule as the confirmation, and for a sharper reason.

        The back-off decides by the clock, not by the request. Applied
        here -- the obvious tidy-up, since all three methods look alike --
        a single failed click would silence the notice for the whole retry
        window, and every registration on a taken address in that window
        would come back shorter than one on a free address.
        """
        queue = CeleryTaskQueue(logger=Mock(), retry_interval=3600)
        with patch(
            "link_shortener.infrastructure.task_queue.tasks.process_link_accessed"
        ) as clicks:
            clicks.delay.side_effect = RuntimeError("broker down")
            queue.enqueue_link_accessed("abc123", context())

        assert queue.enqueue_account_exists_email("u@e.com", context()) is True
        assert task.delay.called


class TestThePasswordResetGoesOutTheSameWay:
    """
    The third message on this queue, and the one nothing published.

    ``enqueue_password_reset_email`` was reached by no test: the method
    was written by copying its neighbour, and a copy that kept the
    neighbour's task name would have mailed a confirmation to somebody
    who asked to reset their password -- with the route answering 202
    either way, because it answers the same thing for every address.
    """

    @pytest.fixture
    def task(self):
        """Replace the Celery task so no broker is involved."""
        with patch(
            "link_shortener.infrastructure.task_queue.tasks."
            "send_password_reset_email"
        ) as task:
            yield task

    def test_it_publishes_the_reset_task_and_not_a_neighbour(self, task):
        with patch(
            "link_shortener.infrastructure.task_queue.tasks."
            "send_verification_email"
        ) as confirmation:
            queue = CeleryTaskQueue(logger=Mock())

            assert queue.enqueue_password_reset_email(
                "u@e.com", "TOK", context()
            ) is True

        assert task.delay.called
        assert not confirmation.delay.called

    def test_it_carries_the_address_the_token_and_the_context(self, task):
        CeleryTaskQueue(logger=Mock()).enqueue_password_reset_email(
            "u@e.com", "TOK", context()
        )

        email, token, ctx = task.delay.call_args.args
        assert (email, token) == ("u@e.com", "TOK")
        assert ctx["request_id"] == "test"

    def test_a_broker_that_refuses_is_reported(self, task):
        task.delay.side_effect = RuntimeError("broker down")
        queue = CeleryTaskQueue(logger=Mock())

        assert queue.enqueue_password_reset_email(
            "u@e.com", "TOK", context()
        ) is False

    def test_the_token_is_not_logged(self, task):
        """A reset token is a way into the account, and a log outlives a
        mailbox."""
        task.delay.side_effect = RuntimeError("broker down")
        logger = Mock()

        CeleryTaskQueue(logger=logger).enqueue_password_reset_email(
            "u@e.com", "SECRET-TOKEN", context()
        )

        assert logger.error.called
        assert "SECRET-TOKEN" not in str(logger.mock_calls)

    def test_a_queue_with_no_logger_still_answers(self, task):
        """The logger is optional, and a refusal must be reported as a
        return value rather than as an AttributeError inside the handler."""
        task.delay.side_effect = RuntimeError("broker down")

        assert CeleryTaskQueue().enqueue_password_reset_email(
            "u@e.com", "TOK", context()
        ) is False

    def test_a_recent_click_failure_does_not_hold_up_a_reset(self, task):
        """Same rule as the other two, and the sharpest reason of the
        three: somebody locked out of their account is turned away
        because a redirect failed a moment ago."""
        queue = CeleryTaskQueue(logger=Mock(), retry_interval=3600)
        with patch(
            "link_shortener.infrastructure.task_queue.tasks.process_link_accessed"
        ) as clicks:
            clicks.delay.side_effect = RuntimeError("broker down")
            queue.enqueue_link_accessed("abc123", context())

        assert queue.enqueue_password_reset_email(
            "u@e.com", "TOK", context()
        ) is True
        assert task.delay.called
