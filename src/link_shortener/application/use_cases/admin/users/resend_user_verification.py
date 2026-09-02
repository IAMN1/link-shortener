from dataclasses import dataclass
from typing import Tuple

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.use_cases.admin.privilege_guard import (
    require_may_act_on_user,
)
from link_shortener.application.use_cases.auth.resend_verification import (
    ResendOutcome,
    ResendVerificationUseCase,
)
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import UserNotFoundError


@dataclass
class ResendUserVerificationUseCase(BaseUseCase):
    """
    Sends an account's confirmation message again, on an operator's word.

    Requires ``admin:manage_users``.

    The operator names an account rather than an address: retyping the
    address is how mail goes to a typo, and the account is what they are
    looking at.

    Its reason for existing separately from ``ResendVerificationUseCase``
    is the reach check. That one is reached by the public endpoint too,
    where the caller is anonymous and there is nobody to check, so the
    check cannot live in it. Without a use case of its own the admin path
    ran the anonymous one directly and the check had nowhere to go --
    which is how this route came to be the only one under
    ``admin:manage_users`` that acted on an account without asking
    whether the caller may reach it.

    What that let through: the message spends every outstanding
    confirmation for the account and issues a new one to its address, so
    a holder of ``admin:manage_users`` could invalidate an unspent
    confirmation link belonging to an account whose permissions they do
    not hold, over and over, and the account would never be able to use
    the link it was sent. ``ConfirmUserEmailUseCase`` refuses the same
    act on the same account for the same reason.

    Attributes:
        uow_factory: Callable that returns a new unit of work.
        resend_verification: The use case the public endpoint also runs,
            which does the sending.
    """

    uow_factory: UnitOfWorkFactory
    resend_verification: ResendVerificationUseCase

    def execute(
        self, user_id: str, context: RequestContext
    ) -> Tuple[str, ResendOutcome]:
        """
        Send the confirmation again to the address of one account.

        Args:
            user_id: UUID of the account.
            context: Request context carrying the operator's identity.

        Returns:
            The address the message was addressed to, and what became of
            the request.

        Raises:
            DomainError: With code ``FORBIDDEN`` if the account holds a
                privileged permission the caller does not.
            UserNotFoundError: With code ``USER_NOT_FOUND`` when no
                account carries that id.
        """
        with self.uow_factory() as uow:
            # Before the lookup, so the refusal a caller is entitled to is
            # the one about their own authority -- the order
            # ``ConfirmUserEmailUseCase`` uses, and for the same reason.
            require_may_act_on_user(context, uow, user_id)

            user = uow.users.find_by_id(user_id)
            if user is None:
                raise UserNotFoundError(user_id)

            address = user.email.value

        # Outside the block: the delegate opens a unit of work of its own,
        # and nothing above needs to be held open across it.
        return address, self.resend_verification.execute(address, context)
