from dataclasses import dataclass
from typing import Callable

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.task_queue import TaskQueue
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import Email
from link_shortener.domain.entities.email_verification import EmailVerification
from link_shortener.domain.value_objects.verification_token import (
    issue_token,
    token_digest,
)


@dataclass
class ResendVerificationUseCase(BaseUseCase):
    """
    Issues a fresh confirmation for an address that has not been proven.

    Answers with the same status and the same sentence whether or not the
    address belongs to anyone, and whether or not it was already
    confirmed. OWASP's Authentication Cheat Sheet gives the shape for the
    neighbouring case -- "If that email address is in our database, we
    will send you an email to reset your password" -- and the reasoning
    carries: a route that will send mail to an address on request is a
    route that will tell anyone who asks whether that address is
    registered.

    The body is level; the timing is not. A registered address takes
    around three times as long as an unknown one, because the branch that
    has something to do issues a token and commits. Closing that would
    mean doing equal work either way, as ``JwtAuthenticationService`` does
    when it hashes against a dummy for an account that does not exist. It
    is not done here, and it is written down in the developer guide.

    Issuing a new token retires the ones outstanding. Otherwise every
    request leaves another working link in the mailbox, and an address is
    confirmed by whichever one is opened -- including one requested by
    somebody else an hour earlier.

    Attributes:
        uow_factory: Factory for Unit of Work instances.
        task_queue: Where the message is handed off.
        logger: Application logger.
        ttl_hours: Lifetime of the confirmation being issued.
    """
    uow_factory: Callable[[], UnitOfWork]
    task_queue: TaskQueue
    logger: Logger
    ttl_hours: int

    def execute(self, email: str, context: RequestContext) -> None:
        """
        Send a new confirmation message, if there is anything to confirm.

        Args:
            email: Address to send to.
            context: Request context.

        Raises:
            ValidationError: If the address is not an address. The format
                is refused because it is refused everywhere, and it says
                nothing about who is registered.
        """
        log = self._get_logger(self.logger, context)

        # Refused before anything is looked up. That is not a defence
        # against timing: a malformed address
        # comes back in 0.12 ms against 0.26 ms for an unknown one and
        # 0.82 ms for a registered one, and the three ranges do not
        # overlap. The status differs too, so the shape of the address was
        # never the secret -- what the ranges do leak is which addresses
        # are registered, and that is written down in the guide rather
        # than papered over here.
        email_vo = Email(email)

        token = None
        with self.uow_factory() as uow:
            user = uow.users.find_by_email(email_vo)
            if user is not None and not user.email_verified:
                uow.email_verifications.invalidate_for_user(user.id)
                token = issue_token()
                uow.email_verifications.save(
                    EmailVerification.issue(
                        user_id=user.id,
                        token_hash=token_digest(token),
                        ttl_hours=self.ttl_hours,
                    )
                )
                uow.commit()

        if token is None:
            # Nothing to send: no such account, or one that is already
            # confirmed. Recorded, because a burst of these is somebody
            # walking a list of addresses, and answered exactly like a
            # success.
            log.info("Verification resend had nothing to send")
            return

        # The normalised address, matching the row the token belongs to.
        if not self.task_queue.enqueue_verification_email(
            email_vo.value, token, context
        ):
            log.error("Verification resend was not handed off")
            return

        log.info("Verification resent")
