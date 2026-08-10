from abc import ABC, abstractmethod


class MailDeliveryError(Exception):
    """
    Raised when a message could not be handed to the mail transport.

    Deliberately not a ``DomainError``. Nothing about the request broke a
    rule -- the address was well formed and the account is allowed to exist
    -- so the caller has nothing to correct and the web layer must not
    answer 400. What failed is a dependency, and the decision about what a
    failed delivery does to the operation belongs to the use case that
    asked for it, not to this port.
    """


class Mailer(ABC):
    """
    Abstract interface for sending a message out of the service.

    Kept to plain strings rather than an ``email.message`` object: that
    class is the SMTP transport's own vocabulary, and a use case that built
    one would be choosing the transport. A provider reached over HTTP takes
    the same three values and never assembles a MIME message at all.
    """

    @abstractmethod
    def send(self, to: str, subject: str, body: str) -> None:
        """
        Send one message.

        Args:
            to: Recipient address. Already validated by the caller -- this
                port does not decide what an address is.
            subject: Subject line, plain text.
            body: Message body, plain text.

        Raises:
            MailDeliveryError: If the message could not be delivered to the
                transport. Callers decide whether that is fatal.
        """
        ...
