from abc import ABC, abstractmethod
from typing import Optional

from link_shortener.domain.entities.password_reset import PasswordReset


class PasswordResetRepository(ABC):
    """
    Interface for reset token persistence.

    Shaped like ``EmailVerificationRepository`` and kept separate from it
    on purpose -- see ``PasswordReset`` for why the two token kinds do not
    share a table. What the similarity buys is that one of them behaving
    differently from the other is visible as a difference in these
    signatures rather than hidden in a filter.
    """

    @abstractmethod
    def save(self, reset: PasswordReset) -> PasswordReset:
        """
        Persist a new or updated reset token.

        Args:
            reset: PasswordReset entity to save.

        Returns:
            The saved PasswordReset.
        """
        ...

    @abstractmethod
    def claim(self, token_hash: str) -> Optional[str]:
        """
        Spend a reset token, losing the race gracefully if one is lost.

        One statement decides it rather than a read followed by a write:
        two requests carrying the same link arrive together often enough,
        and a check-then-act would let both through -- which for this
        token means two password changes from one link.

        Args:
            token_hash: Digest of the token presented by the caller.

        Returns:
            The account the token belongs to, or ``None`` when the token is
            unknown, already spent, or expired -- three cases the caller
            must not be able to tell apart.
        """
        ...

    @abstractmethod
    def invalidate_for_user(self, user_id: str) -> int:
        """
        Spend every reset token an account still has outstanding.

        Called when a new one is issued and again when the password
        changes by any route. The first keeps the newest link the only
        working one; the second is what stops a link mailed before the
        change from still opening the account after it.

        Args:
            user_id: Account whose tokens are retired.

        Returns:
            Number of tokens invalidated.
        """
        ...

    @abstractmethod
    def delete_expired(self) -> int:
        """
        Delete tokens that can no longer be spent.

        Returns:
            Number of rows deleted.
        """
        ...
