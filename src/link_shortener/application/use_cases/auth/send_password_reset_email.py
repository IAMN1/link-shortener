from dataclasses import dataclass
from urllib.parse import quote

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.mail_templates import MailTemplates
from link_shortener.application.ports.mailer import Mailer, MailDeliveryError
from link_shortener.application.use_cases.base_use_case import BaseUseCase


RESET_PATH = "/reset-password"
"""Path the reset link points at.

A page, for the reason ``VERIFY_PATH`` is one: what arrives in a mailbox
is opened by a browser, and the endpoint answers ``application/json``.

Here the page is not merely the better answer -- it is the only one. The
link cannot be a request that does anything: the new password does not
exist until somebody types it, so the token has to survive being opened
and be spent by the form the page carries. A mail scanner following the
link renders a form and spends nothing.
"""


@dataclass
class SendPasswordResetEmailUseCase(BaseUseCase):
    """
    Builds the password reset message for one address and sends it.

    Kept apart from the use case that issues the token for the reason the
    confirmation message is: the background worker and the synchronous
    fallback both run this, so the message is assembled in one place.

    The link is built from configured settings and never from a request
    header. This is the case OWASP's Forgot Password Cheat Sheet names
    outright -- "Don't rely on the Host header while creating the reset
    URLs to avoid Host Header Injection attacks" -- because a ``Host`` an
    attacker chose mails the victim a link to the attacker's server with a
    working reset token on it.

    Attributes:
        mailer: Transport the message is handed to.
        templates: Renderer for the message.
        logger: Application logger.
        base_url: Absolute base the reset link is built on.
        ttl_minutes: Lifetime the message tells the reader about.
    """
    mailer: Mailer
    templates: MailTemplates
    logger: Logger
    base_url: str
    ttl_minutes: int

    def execute(self, email: str, token: str, context: RequestContext) -> None:
        """
        Send one password reset message.

        Args:
            email: Address to send to.
            token: The reset token, in the clear, as it goes into the link.
            context: Request context.

        Raises:
            MailDeliveryError: If the message could not be delivered. The
                caller records it and does not report it -- the route this
                came from answers the same either way.
        """
        log = self._get_logger(self.logger, context)

        # quote() with no safe characters, as in the confirmation link: the
        # token is URL-safe base64 today, and the day that changes a "+"
        # arriving unescaped would be decoded as a space and the link would
        # fail to match its own digest.
        reset_url = (
            f"{self.base_url.rstrip('/')}{RESET_PATH}?token={quote(token, safe='')}"
        )
        subject, body = self.templates.password_reset_email(
            reset_url=reset_url,
            ttl_minutes=self.ttl_minutes,
            # The language the request was answered in, carried on the
            # context because this runs in a worker where the request is
            # long over.
            language=context.language,
        )

        try:
            self.mailer.send(to=email, subject=subject, body=body)
        except MailDeliveryError:
            # Logged without the token or the body. This link is a way into
            # the account for as long as it lives, and a log is read by
            # more people, and kept longer, than a mailbox.
            log.error("Password reset email not delivered", email=email)
            raise

        log.info("Password reset email sent", email=email)
