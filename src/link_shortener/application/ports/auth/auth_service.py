from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from link_shortener.domain import User


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
        Authenticate a user by email and password.

        Args:
            email: User's email.
            password: Raw password.

        Returns:
            User entity if credentials are valid, else None.
        """
        ...

    @abstractmethod
    def create_access_token(self, user: User) -> str:
        """
        Generate a short-lived access token for the user.

        Args:
            user: Authenticated user.

        Returns:
            Signed JWT access token string.
        """
        ...

    @abstractmethod
    def create_refresh_token(self, user: User) -> str:
        """
        Generate a long-lived refresh token for the user.

        Args:
            user: Authenticated user.

        Returns:
            Signed JWT refresh token string.
        """
        ...

    @abstractmethod
    def validate_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Validate a token and return its payload if valid.

        Args:
            token: The JWT to validate.

        Returns:
            Decoded payload dict, or None if invalid/expired.
        """
        ...
    
    @abstractmethod
    def refresh_access_token(self, refresh_token: str) -> Optional[str]:
        """
        Obtain a new access token using a valid refresh token.

        Args:
            refresh_token: The refresh token.

        Returns:
            New access token string, or None if refresh token is invalid.
        """
        ...
