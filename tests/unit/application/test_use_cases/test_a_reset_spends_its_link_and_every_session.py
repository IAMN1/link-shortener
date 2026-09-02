"""What spending a reset link does, and what it refuses to say while doing it.

Every way a token can fail answers the same, and the tests hold that
rather than the code path: "already used" would say an account exists and
somebody reset it, "expired" would say one existed recently, and the two
together turn this route into a way to ask about an address.

The rest is what the reset is for. Every session goes -- the ordinary
reason to reset a password is that somebody else may have it -- and so
does every other reset link outstanding, because one of those is quite
possibly why this happened.
"""

from unittest.mock import Mock

import pytest

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.auth.auth_service import (
    AuthenticationService,
)
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.services.user_management_service import (
    UserManagementService,
)
from link_shortener.application.use_cases.auth.reset_password import (
    ResetPasswordUseCase,
)
from link_shortener.domain import Email, PasswordHash, ValidationError
from link_shortener.domain.entities.user import User


TOKEN = "the-token-from-the-link"
"""What the person is holding, as it arrived in the mail."""


def an_account(is_active: bool = True) -> User:
    """
    The account the token names.

    Args:
        is_active: Whether an administrator has switched it off.

    Returns:
        The user entity.
    """
    user = User.create(
        email=Email("ivanov@example.com"),
        password_hash=PasswordHash("hash-of-the-forgotten-password"),
        roles=[],
    )
    user.is_active = is_active
    user.email_verified = True
    return user


@pytest.fixture
def user():
    """The account under test."""
    return an_account()


@pytest.fixture
def uow(user):
    """A unit of work where the token is good and names that account."""
    unit = Mock()
    unit.__enter__ = Mock(return_value=unit)
    unit.__exit__ = Mock(return_value=False)
    unit.password_resets.claim.return_value = user.id
    unit.users.find_by_id.return_value = user
    unit.refresh_sessions.revoke_all_for_user.return_value = 2
    return unit


@pytest.fixture
def user_service():
    """The real service, over a mocked hasher.

    Not a ``Mock(spec=UserManagementService)``, which is what stood here
    while the retiring lived in this use case. It moved into
    ``update_password`` -- there were three callers and the rule held in
    two -- and mocked away, the service takes the retiring with it and
    the checks below measure nothing. What is mocked is one layer lower:
    hashing, which is bcrypt and has no business in a unit test.
    """
    hasher = Mock(spec=AuthenticationService)
    # A hash a test can recognise. The policy lives inside this call in
    # the real service, which is why the check below for a refused
    # password raises from here rather than from the service.
    hasher.hash_password.side_effect = lambda plain: f"hash-of-{plain}"
    return UserManagementService(
        authentication_service=hasher,
        default_role_name="user",
    )


@pytest.fixture
def audit():
    """The audit logger, watched for the record of the reset.

    ``bind`` answers with the same object, as everywhere else in the
    suite: a child returned here would leave every assertion looking at a
    logger nothing was written to.
    """
    logger = Mock(spec=AuditLogger)
    logger.bind.return_value = logger
    return logger


@pytest.fixture
def use_case(uow, user_service, audit):
    """The use case over mocked collaborators."""
    return ResetPasswordUseCase(
        uow_factory=Mock(return_value=uow),
        user_service=user_service,
        logger=Mock(),
        audit_logger=audit,
    )


@pytest.fixture
def context():
    """An anonymous request: the caller is not signed in and cannot be."""
    return RequestContext(request_id="req-1", remote_addr="203.0.113.7")


class TestATokenThatCannotBeSpent:
    """Four ways to fail, one answer."""

    def test_a_token_the_claim_refuses(self, use_case, uow, context):
        # Unknown, already spent, or expired: `claim` answers None to all
        # three, and so this use case cannot tell them apart even if it
        # wanted to.
        uow.password_resets.claim.return_value = None

        with pytest.raises(ValidationError) as refused:
            use_case.execute(TOKEN, "NewStrong1!", context)

        assert refused.value.field == "token"

    def test_an_account_that_is_gone(self, use_case, uow, context):
        uow.users.find_by_id.return_value = None

        with pytest.raises(ValidationError) as refused:
            use_case.execute(TOKEN, "NewStrong1!", context)

        assert refused.value.field == "token"

    def test_an_account_that_was_switched_off(self, use_case, uow, context):
        uow.users.find_by_id.return_value = an_account(is_active=False)

        with pytest.raises(ValidationError):
            use_case.execute(TOKEN, "NewStrong1!", context)

    def test_the_four_answers_are_one_sentence(self, use_case, uow, context):
        said = []
        for arrange in (
            lambda: setattr(uow.password_resets.claim, "return_value", None),
            lambda: setattr(uow.users.find_by_id, "return_value", None),
            lambda: setattr(
                uow.users.find_by_id, "return_value", an_account(is_active=False)
            ),
        ):
            uow.password_resets.claim.return_value = "u-1"
            uow.users.find_by_id.return_value = an_account()
            arrange()
            with pytest.raises(ValidationError) as refused:
                use_case.execute(TOKEN, "NewStrong1!", context)
            said.append(str(refused.value))

        assert len(set(said)) == 1, said

    def test_nothing_is_written_when_it_fails(
        self, use_case, uow, user_service, audit, context
    ):
        uow.password_resets.claim.return_value = None

        with pytest.raises(ValidationError):
            use_case.execute(TOKEN, "NewStrong1!", context)

        uow.users.save.assert_not_called()
        uow.password_resets.invalidate_for_user.assert_not_called()
        uow.refresh_sessions.revoke_all_for_user.assert_not_called()
        audit.log_password_reset.assert_not_called()
        uow.commit.assert_not_called()


class TestASpentLinkTakesEverythingWithIt:
    """The sessions, and the other links."""

    def test_the_password_is_written(self, use_case, user, uow, context):
        use_case.execute(TOKEN, "NewStrong1!", context)

        uow.users.save.assert_called_once_with(user)
        assert user.password_hash.value == "hash-of-NewStrong1!"

    def test_every_session_is_revoked(self, use_case, user, uow, context):
        use_case.execute(TOKEN, "NewStrong1!", context)

        uow.refresh_sessions.revoke_all_for_user.assert_called_once_with(user.id)

    def test_the_other_links_are_retired(self, use_case, user, uow, context):
        use_case.execute(TOKEN, "NewStrong1!", context)

        # A second link, mailed a minute earlier by whoever caused this,
        # would otherwise still open the account after the reset.
        uow.password_resets.invalidate_for_user.assert_called_once_with(user.id)

    def test_a_password_the_policy_refuses_leaves_nothing_behind(
        self, use_case, uow, user_service, audit, context
    ):
        # Raised from hashing, which is where the policy actually lives:
        # every path that sets a password goes through it, so a rule
        # enforced there is a rule with no way around it.
        user_service.authentication_service.hash_password.side_effect = (
            ValidationError("Password is too common", field="password")
        )

        with pytest.raises(ValidationError):
            use_case.execute(TOKEN, "NewStrong1!", context)

        # No commit, so the claim rolls back with it and the link the
        # person is holding still works for their second attempt.
        uow.commit.assert_not_called()
        uow.refresh_sessions.revoke_all_for_user.assert_not_called()
        audit.log_password_reset.assert_not_called()


class TestTheResetIsRecorded:
    """Its own event, not a password change with a note on it."""

    def test_it_reaches_the_audit_trail(self, use_case, user, audit, context):
        use_case.execute(TOKEN, "NewStrong1!", context)

        audit.log_password_reset.assert_called_once()
        _, kwargs = audit.log_password_reset.call_args
        assert kwargs["target_user_id"] == user.id
        assert kwargs["sessions_revoked"] == 2

    def test_it_is_not_the_other_event(self, use_case, audit, context):
        use_case.execute(TOKEN, "NewStrong1!", context)

        # A reset is somebody who proved they read the mailbox and nothing
        # else; a change is somebody who was already inside. Written as
        # one event, an investigation cannot tell them apart without a
        # filter somebody has to remember to apply.
        audit.log_password_changed.assert_not_called()

    def test_neither_the_token_nor_the_password_is_written_to_it(
        self, use_case, audit, context
    ):
        use_case.execute(TOKEN, "NewStrong1!", context)

        _, kwargs = audit.log_password_reset.call_args
        assert TOKEN not in str(kwargs)
        assert "NewStrong1!" not in str(kwargs)
