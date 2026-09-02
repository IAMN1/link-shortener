"""The budget a sign-in spends per account, and what it refuses to spend it on.

``RATE_LIMITS["auth.login"]`` counts by address. That bounds one guesser
and nobody else: a hundred addresses trying one account are a hundred
separate budgets, so a spray met no counter carrying the account's name.
This budget is that counter.

Two things about it are easy to get wrong, and both are held here. It must
be spent only where the password was **wrong** -- otherwise anyone holding
a valid credential for a deactivated account can lock its owner out by
using it. And its refusal must be indistinguishable from a wrong password
-- otherwise "too many attempts" names an address somebody is interested
in, and the whole point of the uniform refusals on this route is lost.
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


EMAIL = "person@example.com"
PASSWORD = "a-password-of-their-own"


def a_user(is_active: bool = True, email_verified: bool = True) -> User:
    """
    An account in whichever state a test needs.

    Args:
        is_active: Whether an administrator has switched it off.
        email_verified: Whether its address was ever confirmed.

    Returns:
        The user entity.
    """
    user = User.create(
        email=Email(EMAIL),
        password_hash=PasswordHash("$2b$12$" + "x" * 53),
    )
    user.is_active = is_active
    user.email_verified = email_verified
    return user


class RecordingLimiter:
    """A limiter that remembers what it was asked, and answers to order.

    Written out rather than mocked because both halves matter: the test
    has to see the key the use case chose *and* control what is left of
    the budget, and a bare ``Mock`` answers ``get_remaining`` with
    something that cannot be compared to zero.

    Attributes:
        remaining: What ``get_remaining`` will answer.
        spent: Keys ``is_allowed`` was called with, in order.
        asked: Keys ``get_remaining`` was called with, in order.
    """

    def __init__(self, remaining: int = 10):
        """
        Args:
            remaining: The budget this limiter reports as left.
        """
        self.remaining = remaining
        self.spent: list = []
        self.asked: list = []

    def get_remaining(self, key: str, limit: int, period: int) -> int:
        """Report the budget without spending any of it."""
        self.asked.append(key)
        return self.remaining

    def is_allowed(self, key: str, limit: int, period: int) -> bool:
        """Spend one unit of the budget."""
        self.spent.append(key)
        return True


@pytest.fixture
def audit():
    """The audit journal, watched rather than written.

    ``bind`` answers with the same object, for the reason the fixture of
    the same name in ``test_login_reaches_the_audit_trail`` gives: the use
    case binds the request context first, and a mock whose ``bind``
    returned a child would leave every assertion looking at an object
    nothing was written to.
    """
    logger = Mock(spec=AuditLogger)
    logger.bind.return_value = logger
    return logger


@pytest.fixture
def uow_factory():
    """A unit of work that accepts the ``last_login`` write and commits."""
    uow = Mock()
    uow.__enter__ = Mock(return_value=uow)
    uow.__exit__ = Mock(return_value=False)
    return Mock(return_value=uow)


def build(limiter, authenticates, uow_factory, audit, limit=10, period=900):
    """
    Assemble the use case over a limiter and an authentication answer.

    Args:
        limiter: The limiter to count against.
        authenticates: What ``authenticate`` returns.
        uow_factory: Unit of work factory fixture.
        audit: Audit logger fixture.
        limit: The per-account budget.
        period: Its window, in seconds.

    Returns:
        A ``LoginUseCase``.
    """
    service = Mock(spec=AuthenticationService)
    service.authenticate.return_value = authenticates
    service.create_session_tokens.return_value = Mock(
        access_token="access", refresh_token="refresh"
    )

    return LoginUseCase(
        authentication_service=service,
        logger=Mock(),
        uow_factory=uow_factory,
        audit_logger=audit,
        rate_limiter=limiter,
        account_failure_limit=limit,
        account_failure_period=period,
    )


@pytest.fixture
def context():
    """An anonymous request, which is what a sign-in starts as."""
    return RequestContext(request_id="req-1", remote_addr="203.0.113.7")


class TestOnlyAWrongPasswordSpendsIt:
    """What counts as a guess, and what only looks like one."""

    def test_a_wrong_password_spends_one(self, uow_factory, audit, context):
        """The branch the budget exists for."""
        limiter = RecordingLimiter()
        use_case = build(limiter, None, uow_factory, audit)

        with pytest.raises(DomainError):
            use_case.execute(EMAIL, PASSWORD, context)

        assert len(limiter.spent) == 1, "a wrong guess was not counted"

    def test_a_deactivated_account_spends_none(
        self, uow_factory, audit, context
    ):
        """The password was right, so this is not a guess.

        Counting it would hand anyone with an old valid credential a way
        to keep its owner out of the account after it is switched back on.
        """
        limiter = RecordingLimiter()
        use_case = build(
            limiter, a_user(is_active=False), uow_factory, audit
        )

        with pytest.raises(DomainError):
            use_case.execute(EMAIL, PASSWORD, context)

        assert limiter.spent == [], "a correct password spent the budget"

    def test_an_unconfirmed_address_spends_none(
        self, uow_factory, audit, context
    ):
        """The same reasoning: the caller already holds the credential."""
        limiter = RecordingLimiter()
        use_case = build(
            limiter, a_user(email_verified=False), uow_factory, audit
        )

        with pytest.raises(DomainError):
            use_case.execute(EMAIL, PASSWORD, context)

        assert limiter.spent == []

    def test_a_successful_sign_in_spends_none(
        self, uow_factory, audit, context
    ):
        """Nothing is counted against an account that let its owner in."""
        limiter = RecordingLimiter()
        use_case = build(limiter, a_user(), uow_factory, audit)

        use_case.execute(EMAIL, PASSWORD, context)

        assert limiter.spent == []


class TestASpentBudgetRefusesBeforeThePassword:
    """What a caller meets once the budget is gone."""

    def test_the_password_is_not_looked_at(self, uow_factory, audit, context):
        """The point of refusing here rather than after.

        A guess that reaches ``authenticate`` costs bcrypt, which is the
        expense the budget exists to stop paying for a guesser.
        """
        limiter = RecordingLimiter(remaining=0)
        use_case = build(limiter, a_user(), uow_factory, audit)

        with pytest.raises(DomainError):
            use_case.execute(EMAIL, PASSWORD, context)

        assert (
            use_case.authentication_service.authenticate.call_count == 0
        ), "the password was checked after the budget was gone"

    def test_it_answers_as_a_wrong_password_does(
        self, uow_factory, audit, context
    ):
        """The refusal must name nothing the other refusals do not."""
        limiter = RecordingLimiter(remaining=0)
        use_case = build(limiter, a_user(), uow_factory, audit)

        with pytest.raises(DomainError) as refused:
            use_case.execute(EMAIL, PASSWORD, context)

        assert refused.value.code == "INVALID_CREDENTIALS"

    def test_the_journal_is_told_which_it_was(
        self, uow_factory, audit, context
    ):
        """The wire conflates the refusals; the journal separates them."""
        limiter = RecordingLimiter(remaining=0)
        use_case = build(limiter, a_user(), uow_factory, audit)

        with pytest.raises(DomainError):
            use_case.execute(EMAIL, PASSWORD, context)

        audit.log_login_failed.assert_called_once()
        assert (
            audit.log_login_failed.call_args.kwargs["reason"]
            == "too_many_failures"
        )


class TestTheKeyNamesTheAccountAndNotTheAddress:
    """What the counter is keyed on."""

    def test_the_address_is_not_in_the_key(self, uow_factory, audit, context):
        """A cache key is behind no permission; an address belongs behind one."""
        limiter = RecordingLimiter()
        use_case = build(limiter, None, uow_factory, audit)

        with pytest.raises(DomainError):
            use_case.execute(EMAIL, PASSWORD, context)

        assert limiter.spent, "nothing was counted, so there is no key to judge"
        assert EMAIL not in limiter.spent[0]
        assert "example.com" not in limiter.spent[0]

    def test_case_does_not_buy_a_second_budget(
        self, uow_factory, audit, context
    ):
        """``Case@Example.com`` is the same account and the same budget."""
        limiter = RecordingLimiter()
        use_case = build(limiter, None, uow_factory, audit)

        for spelling in (EMAIL, EMAIL.upper(), "Person@Example.com"):
            with pytest.raises(DomainError):
                use_case.execute(spelling, PASSWORD, context)

        assert len(set(limiter.spent)) == 1, (
            "capitalisation opened a second budget"
        )

    def test_an_address_that_is_not_one_is_still_counted(
        self, uow_factory, audit, context
    ):
        """Otherwise the cheapest way past the budget is a malformed address."""
        limiter = RecordingLimiter()
        use_case = build(limiter, None, uow_factory, audit)

        with pytest.raises(DomainError):
            use_case.execute("not-an-address", PASSWORD, context)

        assert len(limiter.spent) == 1


class TestZeroTurnsItOff:
    """The setting that says "count nothing"."""

    def test_nothing_is_asked_and_nothing_is_spent(
        self, uow_factory, audit, context
    ):
        """A disabled budget must not reach the limiter at all.

        Not merely allow: a deployment that turned this off should not be
        paying a round trip per sign-in for an answer it ignores.
        """
        limiter = RecordingLimiter(remaining=0)
        use_case = build(limiter, a_user(), uow_factory, audit, limit=0)

        use_case.execute(EMAIL, PASSWORD, context)

        assert limiter.asked == []
        assert limiter.spent == []
