"""What a password change does besides changing the password.

Two things this use case does are not visible in its return value and are
what the tests below are for. It revokes every session the account had,
and it does that *before* opening the new one -- written the other way
round the caller is signed out by their own change, and the difference is
invisible in any assertion that only looks at the end state.

The third is the refusal to take the change on the session's word. A
session is what somebody who borrowed the laptop already holds, and a
route that skipped the current password would hand them the account.
"""

from unittest.mock import Mock

import pytest

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.auth import RefreshedTokens
from link_shortener.application.ports.auth.auth_service import (
    AuthenticationService,
)
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.services.user_management_service import (
    UserManagementService,
)
from link_shortener.application.use_cases.auth.change_password import (
    ChangePasswordUseCase,
)
from link_shortener.domain import DomainError, Email, PasswordHash, ValidationError
from link_shortener.domain.entities.user import User


CURRENT = "current-password"
"""The password the account is signed in with in these tests."""


def an_account() -> User:
    """
    The account whose password is being changed.

    Returns:
        A confirmed, active user entity.
    """
    user = User.create(
        email=Email("ivanov@example.com"),
        password_hash=PasswordHash("hash-of-the-current-password"),
        roles=[],
    )
    user.email_verified = True
    return user


@pytest.fixture
def user():
    """The account under test."""
    return an_account()


@pytest.fixture
def uow(user):
    """A unit of work whose repositories answer for that one account."""
    unit = Mock()
    unit.__enter__ = Mock(return_value=unit)
    unit.__exit__ = Mock(return_value=False)
    unit.users.find_by_id.return_value = user
    unit.refresh_sessions.revoke_all_for_user.return_value = 3
    return unit


@pytest.fixture
def authentication_service():
    """Authentication that knows exactly one password.

    ``verify_password`` answers by comparing against ``CURRENT`` rather
    than returning a fixed value: the use case asks it twice, once about
    the password presented and once about the one proposed, and a mock
    that always said "yes" would make the second question unanswerable.
    """
    service = Mock(spec=AuthenticationService)
    service.verify_password.side_effect = (
        lambda plain, hashed: plain == CURRENT
    )
    service.create_session_tokens.return_value = RefreshedTokens(
        access_token="new-access", refresh_token="new-refresh"
    )
    return service


@pytest.fixture
def user_service(authentication_service):
    """The real service, over the mocked authentication above.

    Not a ``Mock(spec=UserManagementService)``, which is what stood here
    while the retiring lived in this use case. It moved into
    ``update_password`` -- there were three callers of it and the rule
    held in two -- and mocked away, the service takes the revocation with
    it and the checks below measure nothing. What is mocked is one layer
    lower: hashing, which is bcrypt and has no business in a unit test.
    """
    return UserManagementService(
        authentication_service=authentication_service,
        default_role_name="user",
    )


@pytest.fixture
def audit():
    """The audit logger, watched for the record of the change.

    ``bind`` answers with the same object, as everywhere else in the
    suite: a child returned here would leave every assertion looking at a
    logger nothing was written to.
    """
    logger = Mock(spec=AuditLogger)
    logger.bind.return_value = logger
    return logger


@pytest.fixture
def use_case(uow, authentication_service, user_service, audit):
    """The use case over mocked collaborators."""
    return ChangePasswordUseCase(
        uow_factory=Mock(return_value=uow),
        authentication_service=authentication_service,
        user_service=user_service,
        logger=Mock(),
        audit_logger=audit,
    )


@pytest.fixture
def context():
    """A request made by the account holder."""
    return RequestContext(request_id="req-1", remote_addr="203.0.113.7")


class TestTheCurrentPasswordIsRequired:
    """The check that separates the owner from whoever holds the session."""

    def test_a_wrong_one_is_refused(self, use_case, user, context):
        with pytest.raises(ValidationError) as refused:
            use_case.execute(user.id, "not-the-password", "NewStrong1!", context)

        assert refused.value.field == "current_password"

    def test_nothing_is_written_when_it_is_wrong(
        self, use_case, user, uow, audit, context
    ):
        with pytest.raises(ValidationError):
            use_case.execute(user.id, "not-the-password", "NewStrong1!", context)

        # All four, because each is a separate way for a refused attempt
        # to leave a trace: the password stored, the mailed links retired,
        # the sessions closed, and the journal saying a change happened.
        uow.users.save.assert_not_called()
        uow.password_resets.invalidate_for_user.assert_not_called()
        uow.refresh_sessions.revoke_all_for_user.assert_not_called()
        audit.log_password_changed.assert_not_called()

    def test_repeating_the_current_password_is_refused(
        self, use_case, user, uow, context
    ):
        with pytest.raises(ValidationError) as refused:
            use_case.execute(user.id, CURRENT, CURRENT, context)

        assert refused.value.field == "new_password"
        # The point of refusing it: a change that changes nothing would
        # still close every session and still write a record saying the
        # password was replaced.
        uow.refresh_sessions.revoke_all_for_user.assert_not_called()


class TestEverySessionGoesWithTheChange:
    """Including the caller's own, and in that order."""

    def test_the_sessions_are_revoked(self, use_case, user, uow, context):
        use_case.execute(user.id, CURRENT, "NewStrong1!", context)

        uow.refresh_sessions.revoke_all_for_user.assert_called_once_with(user.id)

    def test_the_new_session_is_opened_after_the_revocation(
        self, use_case, user, uow, authentication_service, context
    ):
        order = Mock()
        order.attach_mock(uow.refresh_sessions.revoke_all_for_user, "revoke")
        order.attach_mock(authentication_service.create_session_tokens, "open")

        use_case.execute(user.id, CURRENT, "NewStrong1!", context)

        # The assertion this file exists for. Opened first, the new session
        # is one of the sessions the next line revokes, and the caller is
        # signed out by their own password change -- with every other
        # assertion here still green.
        assert [call[0] for call in order.mock_calls] == ["revoke", "open"]

    def test_the_caller_is_handed_the_new_pair(self, use_case, user, context):
        tokens = use_case.execute(user.id, CURRENT, "NewStrong1!", context)

        assert tokens.access_token == "new-access"
        assert tokens.refresh_token == "new-refresh"


class TestTheChangeIsRecorded:
    """The event an intrusion is later reconstructed from."""

    def test_it_reaches_the_audit_trail(self, use_case, user, audit, context):
        use_case.execute(user.id, CURRENT, "NewStrong1!", context)

        audit.log_password_changed.assert_called_once()
        _, kwargs = audit.log_password_changed.call_args
        assert kwargs["target_user_id"] == user.id
        # The count of what was thrown out. If one of those three sessions
        # belonged to an intruder, this number is the only trace of it.
        assert kwargs["sessions_revoked"] == 3

    def test_neither_password_is_written_to_it(
        self, use_case, user, audit, context
    ):
        use_case.execute(user.id, CURRENT, "NewStrong1!", context)

        _, kwargs = audit.log_password_changed.call_args
        assert CURRENT not in str(kwargs)
        assert "NewStrong1!" not in str(kwargs)


class TestAnAccountThatWentAway:
    """Authenticated a moment ago, deleted before this transaction read it."""

    def test_it_is_answered_as_unauthenticated(self, use_case, uow, context):
        uow.users.find_by_id.return_value = None

        with pytest.raises(DomainError) as refused:
            use_case.execute("gone", CURRENT, "NewStrong1!", context)

        assert refused.value.code == "UNAUTHENTICATED"
