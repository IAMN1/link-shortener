from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict, Optional

from link_shortener.domain import User

if TYPE_CHECKING:
    # Imported lazily: the DTO module imports from this package, so a plain
    # import would close the cycle.
    from link_shortener.application.dtos.auth import RefreshedTokens


class AuthenticationService(ABC):
    """
    Abstract service responsible for credential verification and JWT management.

    Implementations use specific hashing algorithms and token libraries.
    """

    @abstractmethod
    def hash_password(self, plain: str) -> str:
        """
        Hash a plain-text password for storage.

        Args:
            plain: The raw password.

        Returns:
            Hashed password string.
        """
        ...

    @abstractmethod
    def verify_password(self, plain: str, hashed: str) -> bool:
        """
        Verify a plain-text password against a stored hash.

        Args:
            plain: The raw password.
            hashed: The stored hash.

        Returns:
            True if the password matches.
        """
        ...

    @abstractmethod
    def authenticate(self, email: str, password: str) -> Optional[User]:
        """
        Verify a password against an account.

        Answers one question only -- whether the password matches -- and
        deliberately not whether the account may log in. **A deactivated
        user is returned like any other**, so every caller must check
        ``user.is_active`` itself before granting anything.

        The split is not an oversight. It leaves the caller free to tell the
        two refusals apart in its own logs while answering the client
        identically, which is what hides the difference between a wrong
        password and a disabled account. Deciding it here would collapse
        both into one silent ``None`` and take that signal away.

        Args:
            email: User's email.
            password: Raw password.

        Returns:
            User entity if the password is correct -- active or not --
            else None.
        """
        ...

    @abstractmethod
    def create_session_tokens(self, user: User) -> "RefreshedTokens":
        """
        Open a session for the user and issue its pair of tokens.

        Implementations must issue both together and tie them to the same
        session, so that ending the session ends the access token with it.

        Args:
            user: Authenticated user.

        Returns:
            The access and refresh tokens for the new session.
        """
        ...

    @abstractmethod
    def validate_token(
        self, token: str, expected_type: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Validate a token and return its payload if valid.

        Args:
            token: The JWT to validate.
            expected_type: If provided, the token's ``type`` claim must match
                it ("access" or "refresh"); otherwise the token is rejected.

        Returns:
            Decoded payload dict, or None if invalid/expired.
        """
        ...

    @abstractmethod
    def refresh_access_token(self, refresh_token: str) -> Optional["RefreshedTokens"]:
        """
        Exchange a refresh token for a fresh pair of tokens.

        Implementations must rotate the refresh token: the presented one is
        retired, so a copy of it cannot be spent afterwards. Re-presenting an
        already-spent token indicates the credential leaked and must not
        succeed.

        Args:
            refresh_token: The refresh token.

        Returns:
            The new token pair, or None if the refresh token is invalid,
            already spent, or its account is gone or deactivated.
        """
        ...

    @abstractmethod
    def revoke_refresh_token(self, refresh_token: str) -> bool:
        """
        Retire the session behind a single refresh token.

        Args:
            refresh_token: The refresh token to retire.

        Returns:
            True if a live session was found and revoked.
        """
        ...

    @abstractmethod
    def revoke_session_chain(self, chain_id: str) -> int:
        """
        End a login named by its session chain.

        Lets a client holding only an access token log out, since that token
        names the session it belongs to.

        Args:
            chain_id: Chain to retire.

        Returns:
            Number of sessions revoked.
        """
        ...
