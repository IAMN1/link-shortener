from typing import Optional

from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.mailer import Mailer


class NullMailer(Mailer):
    """
    Null-object implementation of ``Mailer`` for a deployment with no mail.

    Accepts the message and drops it. Not an error: the channel being off
    is a configuration decision, and a service configured without mail has
    to keep serving links. What it costs is stated once, here, rather than
    discovered later -- an account registered while this is in use has no
    way to receive its confirmation.

    The body never reaches the log. It carries the confirmation link, and
    a link is a credential: anything that can read the log could confirm
    the address. The recipient is logged, and only because every log line
    about an account already carries it.

    Attributes:
        logger: Application logger, used to record the dropped message.
    """

    def __init__(self, logger: Optional[Logger] = None):
        """
        Args:
            logger: Application logger for diagnostics.
        """
        self.logger = logger

    def send(self, to: str, subject: str, body: str) -> None:
        """
        Record that a message was asked for and discard it.

        Args:
            to: Recipient address.
            subject: Subject line, plain text.
            body: Message body, plain text. Discarded unread.
        """
        if self.logger:
            self.logger.info(
                "Mail is disabled, message dropped",
                to=to,
                subject=subject,
            )
