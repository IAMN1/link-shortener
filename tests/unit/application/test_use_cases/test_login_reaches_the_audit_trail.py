"""What a sign-in leaves behind, and what it deliberately does not.

The audit journal and the HTTP response answer to different readers, so
they are allowed to say different things -- and on this use case they must.
A deactivated account and a wrong password are one answer over the wire, so
that a guesser learns nothing from the difference; they are two records in
the journal, so that an operator can tell "somebody is guessing passwords"
from "a disabled account's credentials are still in use somewhere".

That divergence is the whole reason these tests exist. Written the obvious
way -- record what the caller was told -- the audit trail would carry three
identical refusals and answer neither question.
"""

from unittest.mock import Mock

import pytest

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.auth.auth_service import (
    AuthenticationService,
)
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.use_cases.auth.login import LoginUseCase
from link_shortener.domain import DomainError, Email, PasswordHash
from link_shortener.domain.entities.user import User


def a_user(is_active: bool = True, email_verified: bool = True) -> User:
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
def audit():
    """The audit logger, watched for what the sign-in writes to it.

    ``bind`` answers with the same object: the use case binds the request
    context before writing, and a mock whose ``bind`` returned a fresh
    child would leave every assertion looking at the unbound original --
    green, and about a logger nothing was written to.
    """
    logger = Mock(spec=AuditLogger)
    logger.bind.return_value = logger
    return logger


@pytest.fixture
def authentication_service():
    """Authentication that refuses everything until a test says otherwise."""
    service = Mock(spec=AuthenticationService)
    service.authenticate.return_value = None
    return service


@pytest.fixture
def uow_factory():
    """A unit of work that accepts the ``last_login`` write and commits."""
    uow = Mock()
    uow.__enter__ = Mock(return_value=uow)
    uow.__exit__ = Mock(return_value=False)
    return Mock(return_value=uow)


@pytest.fixture
def rate_limiter():
    """A limiter with budget left, so these tests meet none of it.

    ``Mock()`` will not do: the use case compares what ``get_remaining``
    answers against zero, and a ``Mock`` is not orderable against an int.
    The budget itself is held by
    ``test_the_account_budget_bounds_a_spray.py``; here it must simply
    stay out of the way.
    """
    limiter = Mock()
    limiter.get_remaining.return_value = 10
    limiter.is_allowed.return_value = True
    return limiter


@pytest.fixture
def use_case(authentication_service, uow_factory, audit, rate_limiter):
    """The use case over mocked collaborators."""
    return LoginUseCase(
        authentication_service=authentication_service,
        logger=Mock(),
        uow_factory=uow_factory,
        audit_logger=audit,
        rate_limiter=rate_limiter,
        account_failure_limit=10,
        account_failure_period=900,
    )


@pytest.fixture
def context():
    """An anonymous request, which is what a sign-in starts as."""
    return RequestContext(request_id="req-1", remote_addr="203.0.113.7")


class TestASuccessfulSignInIsRecorded:
    """The event the counters will later be built on."""

    def test_it_reaches_the_audit_trail(
        self, use_case, authentication_service, audit, context
    ):
        user = a_user()
        authentication_service.authenticate.return_value = user

        use_case.execute("ivanov@example.com", "right", context)

        audit.log_login_succeeded.assert_called_once()
        _, kwargs = audit.log_login_succeeded.call_args
        assert kwargs["target_user_id"] == user.id

    def test_the_request_context_is_bound_to_it(
        self, use_case, authentication_service, audit, context
    ):
        """Where from is half of what a sign-in record is for."""
        authentication_service.authenticate.return_value = a_user()

        use_case.execute("ivanov@example.com", "right", context)

        _, bound = audit.bind.call_args
        assert bound["remote_addr"] == "203.0.113.7"
        assert bound["request_id"] == "req-1"

    def test_nothing_is_recorded_as_failed(
        self, use_case, authentication_service, audit, context
    ):
        authentication_service.authenticate.return_value = a_user()

        use_case.execute("ivanov@example.com", "right", context)

        audit.log_login_failed.assert_not_called()

    def test_it_is_written_only_once_the_session_exists(
        self, use_case, authentication_service, audit, context
    ):
        """A record written ahead of the tokens claims a sign-in that a
        failure in ``create_session_tokens`` never completed."""
        authentication_service.authenticate.return_value = a_user()
        authentication_service.create_session_tokens.side_effect = RuntimeError(
            "the session store is down"
        )

        with pytest.raises(RuntimeError):
            use_case.execute("ivanov@example.com", "right", context)

        audit.log_login_succeeded.assert_not_called()


class TestARefusalIsRecordedWithItsReason:
    """The three refusals, which the response conflates and this does not."""

    def test_wrong_credentials(self, use_case, audit, context):
        with pytest.raises(DomainError):
            use_case.execute("ivanov@example.com", "wrong", context)

        _, kwargs = audit.log_login_failed.call_args
        assert kwargs["reason"] == "invalid_credentials"

    def test_a_deactivated_account_is_not_recorded_as_a_wrong_password(
        self, use_case, authentication_service, audit, context
    ):
        """The divergence this file exists for.

        Over the wire this case is answered exactly like the one above --
        deliberately. In the journal it must not be: the password was
        right, so a live credential is being used against an account
        somebody switched off, and that is the one refusal here that may
        mean the intrusion has already happened.
        """
        user = a_user(is_active=False)
        authentication_service.authenticate.return_value = user

        with pytest.raises(DomainError) as refusal:
            use_case.execute("ivanov@example.com", "right", context)

        assert refusal.value.code == "INVALID_CREDENTIALS"
        _, kwargs = audit.log_login_failed.call_args
        assert kwargs["reason"] == "account_deactivated"
        assert kwargs["target_user_id"] == user.id

    def test_an_unconfirmed_address(
        self, use_case, authentication_service, audit, context
    ):
        user = a_user(email_verified=False)
        authentication_service.authenticate.return_value = user

        with pytest.raises(DomainError):
            use_case.execute("ivanov@example.com", "right", context)

        _, kwargs = audit.log_login_failed.call_args
        assert kwargs["reason"] == "email_not_verified"
        assert kwargs["target_user_id"] == user.id

    @pytest.mark.parametrize(
        "is_active, email_verified",
        [(True, True), (False, True), (True, False)],
    )
    def test_every_outcome_carries_the_address_it_was_about(
        self,
        use_case,
        authentication_service,
        audit,
        context,
        is_active,
        email_verified,
    ):
        """Masked by the adapter, but it has to get there to be masked."""
        authentication_service.authenticate.return_value = a_user(
            is_active=is_active, email_verified=email_verified
        )

        try:
            use_case.execute("ivanov@example.com", "right", context)
        except DomainError:
            pass

        written = (
            audit.log_login_succeeded.call_args
            or audit.log_login_failed.call_args
        )
        assert written is not None, "the outcome reached no audit call at all"
        assert written[1]["email"] == "ivanov@example.com"

    def test_the_reasons_are_distinct_from_one_another(
        self, use_case, authentication_service, audit, context
    ):
        """Three refusals under one reason would answer no question.

        A regression that collapsed them -- reporting the response's code
        rather than the cause -- passes every test above, since each of
        them looks at one case in isolation.
        """
        reasons = []
        for user in (
            None,
            a_user(is_active=False),
            a_user(email_verified=False),
        ):
            authentication_service.authenticate.return_value = user
            with pytest.raises(DomainError):
                use_case.execute("ivanov@example.com", "guess", context)
            reasons.append(audit.log_login_failed.call_args[1]["reason"])

        assert len(set(reasons)) == 3

    def test_an_unknown_account_is_recorded_without_inventing_an_id(
        self, use_case, audit, context
    ):
        """Nothing was authenticated, so there is no account to name."""
        with pytest.raises(DomainError):
            use_case.execute("nobody@example.com", "guess", context)

        _, kwargs = audit.log_login_failed.call_args
        assert "target_user_id" not in kwargs
