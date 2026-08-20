from dataclasses import dataclass
from enum import Enum

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.task_queue import TaskQueue
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import Email
from link_shortener.domain.entities.password_reset import PasswordReset
from link_shortener.domain.value_objects.verification_token import (
    issue_token,
    token_digest,
)


class PasswordResetOutcome(Enum):
    """What became of a request for a reset link.

    Three values rather than a boolean, for the reason ``ResendOutcome``
    has three: "no message went out" has two causes that call for opposite
    reactions. An address with no account behind it needs nothing from
    anybody; a queue that would not take the message needs somebody woken
    up. Collapsed into one flag, the second reads as the first, and a
    broken broker comes out as "nobody has that address".

    The route ignores all three and answers the same either way: which of
    them happened is exactly what it must not disclose. What reads them is
    the journal.
    """

    SENT = "sent"
    """A token was issued and the message handed to the queue."""

    NOTHING_TO_SEND = "nothing_to_send"
    """No such address, or one no reset link may be sent to."""

    NOT_HANDED_OFF = "not_handed_off"
    """The queue refused the message. Nothing will arrive."""


@dataclass
class RequestPasswordResetUseCase(BaseUseCase):
    """
    Issues a reset token for an address and mails the link to it.

    Answers the same whether or not the address belongs to anyone. OWASP's
    Forgot Password Cheat Sheet gives the sentence for it -- "If that email
    address is in our database, we will send you an email to reset your
    password" -- and the reason is the one that governs the whole of this
    service's registration path: a route that mails on request and answers
    honestly is a route that tells anyone who asks who is registered.

    Three states send nothing, and one of them is not obvious. An address
    nobody registered has nothing to send to. A deactivated account cannot
    sign in, so a new password would buy its holder nothing. And an address
    nobody has confirmed is one this service has no evidence belongs to the
    person who typed it -- mailing a reset link there means mailing a way
    into an account to a mailbox that may be somebody else's, on the word
    of whoever registered it. That account's road is the confirmation
    message, which says what it needs to say and grants nothing.

    Issuing a new token retires the ones outstanding. Otherwise every
    request leaves another working link in the mailbox, and the account is
    opened by whichever is used -- including one a stranger asked for an
    hour ago. The alternative, refusing to issue while an earlier one
    lives, hands that stranger a way to block the real owner's request for
    as long as they keep asking.

    The body is level; the timing is not. The branch with something to do
    issues a token and commits, so it takes longer, exactly as the
    confirmation resend does. Closing that would mean doing equal work
    either way; it is written down under "Known limits" in
    ``docs/decisions.md`` rather than papered over here.

    Attributes:
        uow_factory: Factory for Unit of Work instances.
        task_queue: Where the message is handed off.
        logger: Application logger.
        ttl_minutes: Lifetime of the token being issued.
    """
    uow_factory: UnitOfWorkFactory
    task_queue: TaskQueue
    logger: Logger
    ttl_minutes: int

    def execute(
        self, email: str, context: RequestContext
    ) -> PasswordResetOutcome:
        """
        Send a reset link, if there is anywhere to send one.

        Args:
            email: Address to send to.
            context: Request context.

        Returns:
            Which of the three things happened. The route discards it --
            telling the caller apart from the address is the thing that
            route exists not to do.

        Raises:
            ValidationError: If the address is not an address. The format
                is refused because it is refused everywhere, and it says
                nothing about who is registered.
        """
        log = self._get_logger(self.logger, context)

        email_vo = Email(email)

        token = None
        with self.uow_factory() as uow:
            user = uow.users.find_by_email(email_vo)
            if user is not None and user.is_active and user.email_verified:
                uow.password_resets.invalidate_for_user(user.id)
                token = issue_token()
                uow.password_resets.save(
                    PasswordReset.issue(
                        user_id=user.id,
                        token_hash=token_digest(token),
                        ttl_minutes=self.ttl_minutes,
                    )
                )
                uow.commit()

        if token is None:
            # Recorded, because a burst of these is somebody walking a list
            # of addresses, and answered exactly like a success.
            #
            # With the address, which is what makes that reading possible:
            # without it the burst is visible and the list is not, so an
            # operator cannot tell one address retried three hundred times
            # from three hundred addresses tried once -- and only the
            # second is a walk. `application.log` already holds the full
            # address for a registration and for every sign-in, by the
            # decision recorded under the audit journal; what this route
            # withholds it withholds from the *caller*, and the log is a
            # different door with a permission of its own.
            log.info(
                "Password reset had nothing to send", email=email_vo.value
            )
            return PasswordResetOutcome.NOTHING_TO_SEND

        # The normalised address, matching the row the token belongs to.
        if not self.task_queue.enqueue_password_reset_email(
            email_vo.value, token, context
        ):
            log.error(
                "Password reset was not handed off", email=email_vo.value
            )
            return PasswordResetOutcome.NOT_HANDED_OFF

        log.info("Password reset sent", email=email_vo.value)
        return PasswordResetOutcome.SENT
