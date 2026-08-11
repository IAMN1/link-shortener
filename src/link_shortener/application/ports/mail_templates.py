from abc import ABC, abstractmethod
from typing import Tuple


class MailTemplates(ABC):
    """
    Abstract interface for rendering the messages the service sends.

    A port rather than a call to a template engine, because the engine is
    part of the web layer's toolkit and a use case that reached for it
    would be reaching across the layer boundary for a string. What a use
    case knows is which message it wants and what goes in it.
    """

    @abstractmethod
    def verification_email(self, confirm_url: str, ttl_hours: int) -> Tuple[str, str]:
        """
        Render the message that carries a confirmation link.

        Args:
            confirm_url: Absolute URL that confirms the address.
            ttl_hours: How long that URL stays usable, so the message can
                say so -- a link with no stated lifetime is one people
                come back to a week later.

        Returns:
            Tuple of (subject, body), both plain text.
        """
        ...

    @abstractmethod
    def account_exists_email(self, sign_in_url: str) -> Tuple[str, str]:
        """
        Render the message sent when the address is already registered.

        Carries no token and grants nothing. It exists so that a
        registration attempt on a taken address does the same work as one
        on a free address -- the response is already identical, and
        without this the time it takes would not be.

        Args:
            sign_in_url: Absolute URL of the sign-in page, which is all
                this message can offer: the service has no password
                recovery a person can use on their own. An operator can
                reset one with ``flask security reset-password``, and
                that is not something to put in a mail to a stranger.

        Returns:
            Tuple of (subject, body), both plain text.
        """
        ...
