from dataclasses import dataclass

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.user import UserResponse
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import DomainError
from link_shortener.domain.i18n import N_


@dataclass
class ConfirmUserEmailUseCase(BaseUseCase):
    """
    Marks an account's address as confirmed, on an operator's word.

    Requires ``admin:manage_users``.

    Confirmation normally proves one thing: whoever registered can read
    that mailbox. This bypasses the proof, and that is the whole point of
    it -- the mail never arrived, the address is a distribution list
    nobody reads, the deployment has no mail configured at all. Without
    it the only way out is an ``UPDATE`` against the database, which is
    worse in every way: no permission check, no record, no answer.

    So the bypass is made deliberate rather than convenient. It sits
    behind the same permission as suspension and deletion, it says who
    did it in the log, and the interface shows an account's real state
    beside the button rather than after it.

    Outstanding confirmation tokens are spent along with it. A token that
    still works after the address is confirmed is a live credential for
    an account that no longer needs one, and it would sit in a mailbox
    until it expired.
    """

    uow_factory: UnitOfWorkFactory
    logger: Logger

    def execute(self, user_id: str, context: RequestContext) -> UserResponse:
        """
        Confirm an account's address without a mailed link.

        Args:
            user_id: UUID of the account.
            context: Request context carrying the operator's identity.

        Returns:
            UserResponse with the updated state.

        Raises:
            DomainError: With code ``USER_NOT_FOUND`` when no account
                carries that id.
        """
        log = self._get_logger(self.logger, context)

        with self.uow_factory() as uow:
            user = uow.users.find_by_id(user_id)
            if user is None:
                raise DomainError(
                          f"User with id {user_id} not found",
                          code="USER_NOT_FOUND",
                          template=N_("User with id %(id)s not found"),
                          params={"id": user_id},
                      )

            # Already confirmed is not an error: an operator pressing the
            # button twice, or two operators pressing it at once, both
            # want the same end state and both get it.
            already = user.email_verified
            if not already:
                user.confirm_email()
                uow.users.save(user)

            spent = uow.email_verifications.invalidate_for_user(user_id)
            uow.commit()

        # Named in the application log rather than the audit journal: the
        # audit port carries link events and nothing about accounts, and
        # widening a port is a larger decision than this change.
        log.info(
            "Email confirmed by an administrator",
            target_user_id=user_id,
            was_already_confirmed=already,
            tokens_invalidated=spent,
        )

        return UserResponse.from_user(user)
