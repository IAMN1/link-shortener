from dataclasses import dataclass

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.mail_templates import MailTemplates
from link_shortener.application.ports.mailer import Mailer, MailDeliveryError
from link_shortener.application.use_cases.base_use_case import BaseUseCase


SIGN_IN_PATH = "/login"
"""Path of the sign-in page the message points at."""


@dataclass
class SendAccountExistsEmailUseCase(BaseUseCase):
    """
    Tells an address that somebody tried to register it again.

    Sent instead of refusing the registration out loud. The refusal used
    to be the response -- 400 and "Email already registered" -- which
    answered, for anyone who asked, whether an address has an account
    here. OWASP's Authentication Cheat Sheet asks for the opposite under
    *Account creation*: the correct response it gives is "A link to
    activate your account has been emailed to the address provided", and
    it lists "This user ID is already in use." among the incorrect ones.

    The message carries no token and grants nothing, so it is safe to
    send to an address whoever typed it may not own. What it does carry
    is the news that somebody tried, which is worth knowing.

    Sending it is also what keeps the two registration paths the same
    length. A taken address and a free one both hash a password and both
    submit one message, so neither the body nor the clock separates them.
    Skipping the message here would reopen the timing channel that the
    equal bodies are meant to close: one submission costs milliseconds
    against a local catcher and more against a remote relay.

    Attributes:
        mailer: Transport the message is handed to.
        templates: Renderer for the message.
        logger: Application logger.
        base_url: Absolute base the sign-in link is built on.
    """
    mailer: Mailer
    templates: MailTemplates
    logger: Logger
    base_url: str

    def execute(self, email: str, context: RequestContext) -> None:
        """
        Send one "this address is already registered" message.

        Args:
            email: Address to send to.
            context: Request context.

        Raises:
            MailDeliveryError: If the message could not be delivered. The
                caller decides what that means; registration treats it as
                a message nobody was waiting for and carries on, because
                the response must not depend on it.
        """
        log = self._get_logger(self.logger, context)

        sign_in_url = f"{self.base_url.rstrip('/')}{SIGN_IN_PATH}"
        subject, body = self.templates.account_exists_email(
            sign_in_url=sign_in_url, language=context.language
        )

        try:
            self.mailer.send(to=email, subject=subject, body=body)
        except MailDeliveryError:
            log.error("Account-exists notice not delivered", email=email)
            raise

        log.info("Account-exists notice sent", email=email)
