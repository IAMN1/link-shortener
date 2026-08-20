"""A burst of mail-on-request calls has to say *which* addresses.

``resend_verification`` and ``forgot_password`` answer the same for every
address on purpose: telling them apart is what those routes exist not to
do. Both use cases record the outcome anyway, and the comment beside each
record says why -- "a burst of these is somebody walking a list of
addresses".

The record could not carry that reading. Every line either use case wrote
named the outcome and nothing else, so a hundred of them meant "this
happened a hundred times" and never "to a hundred different addresses" --
and only the second is a walk. It is the difference between a person who
mistyped their address four times and somebody testing a breach dump
against this service, and it was not in the journal.

The address goes in ``application.log``, not in the audit journal, and not
into any answer. That is the door it was already going through for a
registration and for every sign-in, recorded under "The audit journal
records what the service does about accounts" in ``docs/decisions.md``:
the audit journal masks the address, ``application.log`` keeps it, and the
two open to different permissions. What these routes withhold, they
withhold from the caller.
"""

from unittest.mock import Mock

import pytest

from link_shortener.application.context import RequestContext
from link_shortener.application.use_cases.auth.request_password_reset import (
    RequestPasswordResetUseCase,
)
from link_shortener.application.use_cases.auth.resend_verification import (
    ResendVerificationUseCase,
)
from link_shortener.domain import Email, PasswordHash
from link_shortener.domain.entities.user import User


WALKED = "Someone.Else@Example.COM"
"""Typed as an attacker would send it, mixed case and all.

What lands in the journal has to be the normalised form: that is the
spelling the account is stored under, and two spellings of one address
read as two addresses to whoever is counting them."""

NORMALISED = "someone.else@example.com"


def an_account(email_verified: bool = True, is_active: bool = True) -> User:
    """
    An account in whichever state a test needs.

    Args:
        email_verified: Whether its address was ever confirmed.
        is_active: Whether an administrator has switched it off.

    Returns:
        The user entity.
    """
    user = User.create(
        email=Email(NORMALISED),
        password_hash=PasswordHash("not-checked-here"),
        roles=[],
    )
    user.email_verified = email_verified
    user.is_active = is_active
    return user


@pytest.fixture
def uow():
    """A unit of work whose lookup answers with nobody, by default."""
    unit = Mock()
    unit.__enter__ = Mock(return_value=unit)
    unit.__exit__ = Mock(return_value=False)
    unit.users.find_by_email.return_value = None
    return unit


@pytest.fixture
def logger():
    """A logger that hands back itself when bound, so calls are visible."""
    log = Mock()
    log.bind.return_value = log
    return log


def said(logger):
    """
    Every field every call put in the journal.

    Args:
        logger: The logger a use case was given.

    Returns:
        List of ``(message, fields)`` pairs.
    """
    return [
        (call.args[0] if call.args else "", call.kwargs)
        for call in logger.info.call_args_list + logger.error.call_args_list
    ]


class TestTheResendRoute:

    @pytest.fixture
    def use_case(self, uow, logger):
        queue = Mock()
        queue.enqueue_verification_email.return_value = True
        return ResendVerificationUseCase(
            uow_factory=lambda *a, **k: uow,
            task_queue=queue,
            logger=logger,
            ttl_hours=24,
        )

    def test_an_address_with_nothing_to_send_to_is_named(
        self, use_case, logger
    ):
        use_case.execute(WALKED, RequestContext(request_id="walk"))

        assert any(
            fields.get("email") == NORMALISED for _, fields in said(logger)
        ), f"nothing in the journal names the address: {said(logger)}"

    def test_an_address_that_is_sent_one_is_named_too(
        self, use_case, uow, logger
    ):
        uow.users.find_by_email.return_value = an_account(email_verified=False)

        use_case.execute(WALKED, RequestContext(request_id="walk"))

        assert any(
            fields.get("email") == NORMALISED for _, fields in said(logger)
        ), f"nothing in the journal names the address: {said(logger)}"


class TestTheForgottenPasswordRoute:

    @pytest.fixture
    def use_case(self, uow, logger):
        queue = Mock()
        queue.enqueue_password_reset_email.return_value = True
        return RequestPasswordResetUseCase(
            uow_factory=lambda *a, **k: uow,
            task_queue=queue,
            logger=logger,
            ttl_minutes=60,
        )

    def test_an_address_with_nothing_to_send_to_is_named(
        self, use_case, logger
    ):
        use_case.execute(WALKED, RequestContext(request_id="walk"))

        assert any(
            fields.get("email") == NORMALISED for _, fields in said(logger)
        ), f"nothing in the journal names the address: {said(logger)}"

    def test_an_address_that_is_sent_one_is_named_too(
        self, use_case, uow, logger
    ):
        uow.users.find_by_email.return_value = an_account()

        use_case.execute(WALKED, RequestContext(request_id="walk"))

        assert any(
            fields.get("email") == NORMALISED for _, fields in said(logger)
        ), f"nothing in the journal names the address: {said(logger)}"

    def test_a_queue_that_would_not_take_it_names_the_address(
        self, use_case, uow, logger
    ):
        """The line an operator is woken by is the one that must be legible."""
        uow.users.find_by_email.return_value = an_account()
        use_case.task_queue.enqueue_password_reset_email.return_value = False

        use_case.execute(WALKED, RequestContext(request_id="walk"))

        assert any(
            fields.get("email") == NORMALISED
            for _, fields in said(logger)
        ), f"nothing in the journal names the address: {said(logger)}"
