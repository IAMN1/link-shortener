from abc import ABC, abstractmethod
from typing import Optional, Tuple


class MailTemplates(ABC):
    """
    Abstract interface for rendering the messages the service sends.

    A port rather than a call to a template engine, because the engine is
    part of the web layer's toolkit and a use case that reached for it
    would be reaching across the layer boundary for a string. What a use
    case knows is which message it wants and what goes in it.
    """

    @abstractmethod
    def verification_email(
        self,
        confirm_url: str,
        ttl_hours: int,
        language: Optional[str] = None,
    ) -> Tuple[str, str]:
        """
        Render the message that carries a confirmation link.

        Args:
            confirm_url: Absolute URL that confirms the address.
            ttl_hours: How long that URL stays usable, so the message can
                say so -- a link with no stated lifetime is one people
                come back to a week later.
            language: Language tag the request that asked for this message
                was answered in. ``None`` means nobody chose, and the
                configured default is used.

        Returns:
            Tuple of (subject, body), both plain text.
        """
        ...

    @abstractmethod
    def password_reset_email(
        self,
        reset_url: str,
        ttl_minutes: int,
        language: Optional[str] = None,
    ) -> Tuple[str, str]:
        """
        Render the message that carries a password reset link.

        Args:
            reset_url: Absolute URL that opens the reset form.
            ttl_minutes: How long that URL stays usable, so the message can
                say so. Stated in minutes rather than hours because this
                link is short-lived on purpose, and a reader who is not
                told that comes back to it in the evening.
            language: Language tag the request that asked for this message
                was answered in. ``None`` means nobody chose, and the
                configured default is used.

        Returns:
            Tuple of (subject, body), both plain text.
        """
        ...

    @abstractmethod
    def account_exists_email(
        self, sign_in_url: str, language: Optional[str] = None
    ) -> Tuple[str, str]:
        """
        Render the message sent when the address is already registered.

        Carries no token and grants nothing. It exists so that a
        registration attempt on a taken address does the same work as one
        on a free address -- the response is already identical, and
        without this the time it takes would not be.

        Args:
            sign_in_url: Absolute URL of the sign-in page. That page
                carries the way on to password recovery, which is where
                this message's likeliest reader is going: somebody
                registering an address they already hold is usually
                somebody who forgot they hold it.
            language: Language tag, as above.

        Returns:
            Tuple of (subject, body), both plain text.
        """
        ...
