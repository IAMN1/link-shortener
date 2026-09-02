"""What the Celery tasks do when a worker actually runs them.

Everything else about the queue is tested with the task itself patched
out -- which checks that publishing happens and says nothing about what
the worker does with the message. The bodies live in a module a worker
imports and the suite otherwise never executes, so a task that reaches
for the wrong use case, or hands it the wrong arguments, was invisible:
the publish-side tests stay green because they never get that far.

The mail tasks are near-copies of each other, which is exactly the
shape that produces a wrong getter under copy-paste.
"""

from unittest.mock import Mock, patch

import pytest

from link_shortener.infrastructure.task_queue import tasks


CONTEXT = {
    "request_id": "test",
    "remote_addr": "10.0.0.1",
    "user_agent": "agent",
    "request_path": "/api/v1/auth/register",
    "request_method": "POST",
}


@pytest.fixture
def container():
    """A container whose use cases record what the worker asked of them.

    Both getters are distinct mocks, so a task reaching for its
    neighbour's use case is a call on the wrong one rather than a call
    that merely looks similar.
    """
    fake = Mock()
    fake.get_send_verification_email_use_case.return_value = Mock()
    fake.get_send_account_exists_email_use_case.return_value = Mock()
    fake.get_update_link_stats_use_case.return_value = Mock()
    fake.get_send_password_reset_email_use_case.return_value = Mock()
    with patch.object(tasks, "get_container", return_value=fake):
        yield fake


class TestTheConfirmationTask:
    """``send_verification_email`` as a worker runs it."""

    def test_it_uses_the_confirmation_use_case(self, container):
        tasks.send_verification_email.run("u@e.com", "TOK", CONTEXT)

        container.get_send_verification_email_use_case.assert_called_once()
        container.get_send_account_exists_email_use_case.assert_not_called()

    def test_it_passes_the_address_the_token_and_the_context(self, container):
        tasks.send_verification_email.run("u@e.com", "TOK", CONTEXT)

        use_case = container.get_send_verification_email_use_case.return_value
        email, token, ctx = use_case.execute.call_args.args
        assert (email, token) == ("u@e.com", "TOK")
        assert ctx.request_id == "test"


class TestTheAccountExistsTask:
    """``send_account_exists_email`` as a worker runs it."""

    def test_it_uses_the_account_exists_use_case(self, container):
        """The copy-paste check. Reaching for the confirmation use case
        here would call it with two arguments where it takes three -- a
        TypeError on the worker, three retries, and no message ever sent,
        while registration answered 202."""
        tasks.send_account_exists_email.run("u@e.com", CONTEXT)

        container.get_send_account_exists_email_use_case.assert_called_once()
        container.get_send_verification_email_use_case.assert_not_called()

    def test_it_passes_the_address_and_the_context(self, container):
        tasks.send_account_exists_email.run("u@e.com", CONTEXT)

        use_case = container.get_send_account_exists_email_use_case.return_value
        email, ctx = use_case.execute.call_args.args
        assert email == "u@e.com"
        assert ctx.request_id == "test"

    def test_it_carries_no_token_to_carry(self, container):
        """Two arguments, not three. The notice grants nothing, and there
        is no credential for a broker to hold on its behalf."""
        tasks.send_account_exists_email.run("u@e.com", CONTEXT)

        use_case = container.get_send_account_exists_email_use_case.return_value
        assert len(use_case.execute.call_args.args) == 2


class TestAFailingSendIsRetried:
    """A submission server that is briefly unreachable is the ordinary
    case, and the person waiting has no other way to get the message."""

    def test_the_confirmation_task_retries(self, container):
        use_case = container.get_send_verification_email_use_case.return_value
        use_case.execute.side_effect = RuntimeError("smtp down")

        with patch.object(tasks.send_verification_email, "retry") as retry:
            tasks.send_verification_email.run("u@e.com", "TOK", CONTEXT)

        assert retry.called

    def test_the_notice_task_retries(self, container):
        use_case = container.get_send_account_exists_email_use_case.return_value
        use_case.execute.side_effect = RuntimeError("smtp down")

        with patch.object(tasks.send_account_exists_email, "retry") as retry:
            tasks.send_account_exists_email.run("u@e.com", CONTEXT)

        assert retry.called

    def test_a_failing_confirmation_does_not_log_the_token(self, container):
        """The body is not logged and neither is the link; the token is a
        working credential until it is spent."""
        use_case = container.get_send_verification_email_use_case.return_value
        use_case.execute.side_effect = RuntimeError("smtp down")

        with patch.object(tasks, "logger") as logger:
            with patch.object(tasks.send_verification_email, "retry"):
                tasks.send_verification_email.run(
                    "u@e.com", "SECRET-TOKEN", CONTEXT
                )

        assert "SECRET-TOKEN" not in str(logger.mock_calls)


class TestThePasswordResetTask:
    """``send_password_reset_email`` as a worker runs it.

    The third near-copy, and the one nothing ran: the body was reached by
    no test at all, so a getter copied from the neighbour above would
    have sent a confirmation where a reset was asked for -- with
    ``/api/v1/auth/forgot-password`` still answering 202.
    """

    def test_it_uses_the_password_reset_use_case(self, container):
        tasks.send_password_reset_email.run("u@e.com", "TOK", CONTEXT)

        container.get_send_password_reset_email_use_case.assert_called_once()
        container.get_send_verification_email_use_case.assert_not_called()
        container.get_send_account_exists_email_use_case.assert_not_called()

    def test_it_passes_the_address_the_token_and_the_context(self, container):
        tasks.send_password_reset_email.run("u@e.com", "TOK", CONTEXT)

        use_case = container.get_send_password_reset_email_use_case.return_value
        email, token, ctx = use_case.execute.call_args.args
        assert (email, token) == ("u@e.com", "TOK")
        assert ctx.request_id == "test"

    def test_a_failing_send_is_retried(self, container):
        use_case = container.get_send_password_reset_email_use_case.return_value
        use_case.execute.side_effect = RuntimeError("smtp down")

        with patch.object(tasks.send_password_reset_email, "retry") as retry:
            tasks.send_password_reset_email.run("u@e.com", "TOK", CONTEXT)

        assert retry.called

    def test_a_failing_send_does_not_log_the_token(self, container):
        """This token is a way into the account, so of the tokens the
        tasks carry it is the one that matters most."""
        use_case = container.get_send_password_reset_email_use_case.return_value
        use_case.execute.side_effect = RuntimeError("smtp down")

        with patch.object(tasks, "logger") as logger:
            with patch.object(tasks.send_password_reset_email, "retry"):
                tasks.send_password_reset_email.run(
                    "u@e.com", "SECRET-TOKEN", CONTEXT
                )

        assert "SECRET-TOKEN" not in str(logger.mock_calls)


class TestTheClickCounterTaskWhenItCannotCount:
    """The counter's failure path, which nothing had run.

    A redirect has already been answered by the time this task runs, so
    the failure is invisible to the person who clicked -- which is
    precisely why it has to reach the journal and the retry rather than
    being dropped.
    """

    def test_a_failing_update_is_retried(self, container):
        use_case = container.get_update_link_stats_use_case.return_value
        use_case.execute.side_effect = RuntimeError("database down")

        with patch.object(tasks.process_link_accessed, "retry") as retry:
            tasks.process_link_accessed.run("abc123", CONTEXT)

        assert retry.called

    def test_the_failure_reaches_the_journal(self, container):
        use_case = container.get_update_link_stats_use_case.return_value
        use_case.execute.side_effect = RuntimeError("database down")

        with patch.object(tasks, "logger") as logger:
            with patch.object(tasks.process_link_accessed, "retry"):
                tasks.process_link_accessed.run("abc123", CONTEXT)

        assert logger.exception.called


class TestTheContainerAWorkerBuilds:
    """
    A worker has no application around it, so each task builds its own.

    Nothing executed this function: every test above replaces it. What it
    holds is that the worker's container is built from the configuration
    the profile names, rather than from defaults -- a worker on the wrong
    settings sends mail through the wrong server and writes to the wrong
    database.
    """

    def test_it_builds_the_container_from_the_configuration(self):
        config = Mock()
        with patch.object(tasks, "get_config", return_value=config) as read:
            with patch.object(tasks, "Container") as container_class:
                built = tasks.get_container()

        read.assert_called_once()
        container_class.assert_called_once_with(config)
        assert built is container_class.return_value
