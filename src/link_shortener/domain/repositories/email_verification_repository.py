from abc import ABC, abstractmethod
from typing import Optional

from link_shortener.domain.entities.email_verification import EmailVerification


class EmailVerificationRepository(ABC):
    """
    Interface for confirmation token persistence.

    All methods define what needs to be done without prescribing how; the
    infrastructure layer provides concrete implementations.
    """

    @abstractmethod
    def save(self, verification: EmailVerification) -> EmailVerification:
        """
        Persist a new or updated confirmation.

        Args:
            verification: EmailVerification entity to save.

        Returns:
            The saved EmailVerification.
        """
        ...

    @abstractmethod
    def claim(self, token_hash: str) -> Optional[str]:
        """
        Spend a confirmation, losing the race gracefully if one is lost.

        One statement decides it, rather than a read followed by a write:
        two requests carrying the same link arrive together often enough
        (a mail client that prefetches, a double click), and a check-then-
        act would let both through. Only one caller may be told which
        account the token confirms.

        Args:
            token_hash: Digest of the token presented by the caller.

        Returns:
            The account the token belongs to, or ``None`` when the token is
            unknown, already spent, or expired -- three cases the caller
            must not be able to tell apart.
        """
        ...

    @abstractmethod
    def find_by_token_hash(self, token_hash: str) -> Optional[EmailVerification]:
        """
        Look up a confirmation by the digest of its token.

        Args:
            token_hash: Digest of the token.

        Returns:
            EmailVerification if found, otherwise None. Found does not mean
            usable -- ``claim`` is what decides that.
        """
        ...

    @abstractmethod
    def invalidate_for_user(self, user_id: str) -> int:
        """
        Spend every confirmation an account still has outstanding.

        Called when a new one is issued, so that an address confirmed by
        the newest link cannot also be confirmed by an older one still
        sitting in the mailbox -- and again when an administrator confirms
        the address outright, which leaves every link already mailed for it
        with nothing left to confirm.

        Args:
            user_id: Account whose confirmations are retired.

        Returns:
            Number of confirmations invalidated.
        """
        ...

    @abstractmethod
    def delete_expired(self) -> int:
        """
        Delete confirmations that can no longer be spent.

        Returns:
            Number of rows deleted.
        """
        ...
