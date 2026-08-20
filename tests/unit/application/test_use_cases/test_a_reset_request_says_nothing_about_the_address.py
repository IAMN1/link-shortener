"""Who gets a reset link, and what the route may not disclose by sending one.

Three kinds of address get nothing, and the interesting one is the third.
An address nobody registered has no account. A deactivated account cannot
sign in, so a new password buys its holder nothing. And an unconfirmed
address is one this service has no evidence about at all -- mailing a way
into an account there means mailing it to a mailbox that may belong to
somebody else, on the word of whoever typed it into the registration form.

All three answer like a success, which is the whole shape of the route, so
the tests below read the outcome the use case returns rather than the
response: the response is where the difference is deliberately gone.
"""

from unittest.mock import Mock

import pytest

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.task_queue import TaskQueue
from link_shortener.application.use_cases.auth.request_password_reset import (
    PasswordResetOutcome,
    RequestPasswordResetUseCase,
)
from link_shortener.domain import Email, PasswordHash, ValidationError
from link_shortener.domain.entities.user import User


TTL_MINUTES = 60
"""The lifetime the use case is configured with in these tests."""


def an_account(is_active: bool = True, email_verified: bool = True) -> User:
    """
    An account in whichever of the three states a test needs.

    Args:
        is_active: Whether an administrator has switched it off.
        email_verified: Whether its address was ever confirmed.

    Returns:
        The user entity.
    """
    user = User.create(
        email=Email("ivanov@example.com"),
        password_hash=PasswordHash("not-checked-here"),
        roles=[],
    )
    user.is_active = is_active
    user.email_verified = email_verified
    return user


@pytest.fixture
def uow():
    """A unit of work whose user lookup answers with nobody, by default."""
    unit = Mock()
    unit.__enter__ = Mock(return_value=unit)
    unit.__exit__ = Mock(return_value=False)
    unit.users.find_by_email.return_value = None
    return unit


@pytest.fixture
def task_queue():
    """A queue that accepts whatever it is handed."""
    queue = Mock(spec=TaskQueue)
    queue.enqueue_password_reset_email.return_value = True
    return queue


@pytest.fixture
def use_case(uow, task_queue):
    """The use case over mocked collaborators."""
    return RequestPasswordResetUseCase(
        uow_factory=Mock(return_value=uow),
        task_queue=task_queue,
        logger=Mock(),
        ttl_minutes=TTL_MINUTES,
    )


@pytest.fixture
def context():
    """An anonymous request, which is what this always is."""
    return RequestContext(request_id="req-1", remote_addr="203.0.113.7")


class TestNothingIsSentTo:
    """The three addresses that get no link, and leave no token behind."""

    @pytest.mark.parametrize(
        "user, why",
        [
            (None, "no account"),
            (an_account(is_active=False), "deactivated"),
            (an_account(email_verified=False), "unconfirmed"),
        ],
    )
    def test_no_token_is_issued(self, use_case, uow, task_queue, context, user, why):
        uow.users.find_by_email.return_value = user

        outcome = use_case.execute("ivanov@example.com", context)

        assert outcome is PasswordResetOutcome.NOTHING_TO_SEND, why
        uow.password_resets.save.assert_not_called()
        task_queue.enqueue_password_reset_email.assert_not_called()

    def test_a_malformed_address_is_refused(self, use_case, context):
        # Refused on its own merits, and the status differs -- which says
        # nothing about who is registered, because the shape of an address
        # is not a fact about this service.
        with pytest.raises(ValidationError):
            use_case.execute("not-an-address", context)


class TestALiveAccountIsSentOne:
    """The one branch that issues a token."""

    def test_the_token_is_stored_and_the_message_handed_off(
        self, use_case, uow, task_queue, context
    ):
        uow.users.find_by_email.return_value = an_account()

        outcome = use_case.execute("ivanov@example.com", context)

        assert outcome is PasswordResetOutcome.SENT
        uow.password_resets.save.assert_called_once()
        task_queue.enqueue_password_reset_email.assert_called_once()

    def test_only_the_digest_is_stored(self, use_case, uow, task_queue, context):
        uow.users.find_by_email.return_value = an_account()

        use_case.execute("ivanov@example.com", context)

        stored = uow.password_resets.save.call_args[0][0]
        mailed = task_queue.enqueue_password_reset_email.call_args[0][1]
        # The row must not be the link. A database read out of a backup is
        # then worth nothing on its own.
        assert stored.token_hash != mailed
        assert mailed not in stored.token_hash

    def test_the_earlier_links_are_retired_first(
        self, use_case, uow, context
    ):
        uow.users.find_by_email.return_value = an_account()

        use_case.execute("ivanov@example.com", context)

        order = [call[0] for call in uow.password_resets.mock_calls]
        # Retired before the new one is written, not after: the other way
        # round the request that was supposed to leave one working link
        # leaves none.
        assert order[:2] == ["invalidate_for_user", "save"]

    def test_a_queue_that_refuses_is_reported_apart(
        self, use_case, uow, task_queue, context
    ):
        uow.users.find_by_email.return_value = an_account()
        task_queue.enqueue_password_reset_email.return_value = False

        outcome = use_case.execute("ivanov@example.com", context)

        # Not NOTHING_TO_SEND. Collapsed into that, a broken broker reads
        # as "nobody has that address" and nobody is woken up.
        assert outcome is PasswordResetOutcome.NOT_HANDED_OFF
