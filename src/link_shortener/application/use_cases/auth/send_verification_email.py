from dataclasses import dataclass
from urllib.parse import quote

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.mail_templates import MailTemplates
from link_shortener.application.ports.mailer import Mailer, MailDeliveryError
from link_shortener.application.use_cases.base_use_case import BaseUseCase


VERIFY_PATH = "/verify"
"""Path the confirmation link points at.

A page, not the API endpoint. What arrives in a mailbox is opened by a
browser, and the endpoint answers ``application/json``: the person who did
what the message asked was shown ``{"message": "Email confirmed..."}`` and
left to work out where to sign in.

The page also decides when the token is spent. Confirming from a link the
mail client fetched is a state change behind a GET, and scanners that
follow links spend the token before its owner opens the message -- who
then reads that their confirmation is invalid. The page asks for a click,
and that click is the POST.

The endpoint still answers GET, so links mailed before this change go on
working.
"""


@dataclass
class SendVerificationEmailUseCase(BaseUseCase):
    """
    Builds the confirmation message for one address and sends it.

    Kept apart from registration so that both the background worker and
    the synchronous fallback run the same code -- the alternative was the
    message being assembled in two places, which is how the two come to
    differ.

    The link is built from configured settings and never from a request
    header. OWASP's Forgot Password Cheat Sheet asks exactly this: "Don't
    rely on the Host header while creating the reset URLs to avoid Host
    Header Injection attacks. The URL should either be hard-coded, or
    validated against a list of trusted domains." A ``Host`` an attacker
    chose would mail the victim a link to the attacker's server, carrying
    a working token.

    Attributes:
        mailer: Transport the message is handed to.
        templates: Renderer for the message.
        logger: Application logger.
        base_url: Absolute base the confirmation link is built on.
        ttl_hours: Lifetime the message tells the reader about.
    """
    mailer: Mailer
    templates: MailTemplates
    logger: Logger
    base_url: str
    ttl_hours: int

    def execute(self, email: str, token: str, context: RequestContext) -> None:
        """
        Send one confirmation message.

        Args:
            email: Address to send to.
            token: The confirmation token, in the clear, as it goes into
                the link.
            context: Request context.

        Raises:
            MailDeliveryError: If the message could not be delivered. The
                caller decides what that means; registration treats it as
                a message the user can ask for again.
        """
        log = self._get_logger(self.logger, context)

        # quote() with no safe characters: the token is URL-safe base64 by
        # construction, so this changes nothing today. It is here because
        # the day the token format changes, a "+" or "/" arriving unescaped
        # would be decoded as a space or a path separator, and the link
        # would fail to match its own digest.
        confirm_url = (
            f"{self.base_url.rstrip('/')}{VERIFY_PATH}?token={quote(token, safe='')}"
        )
        subject, body = self.templates.verification_email(
            confirm_url=confirm_url,
            ttl_hours=self.ttl_hours,
            # The language the registration was answered in, carried on
            # the context because this runs in a worker where the request
            # is long over.
            language=context.language,
        )

        try:
            self.mailer.send(to=email, subject=subject, body=body)
        except MailDeliveryError:
            # Logged without the token or the body. The link is a
            # credential for exactly as long as it is valid, and a log is
            # read by more people, and kept longer, than a mailbox.
            log.error("Verification email not delivered", email=email)
            raise

        log.info("Verification email sent", email=email)
