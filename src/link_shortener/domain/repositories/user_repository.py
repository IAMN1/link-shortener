from abc import ABC, abstractmethod
from typing import List, Optional

from link_shortener.domain.entities.user import User
from link_shortener.domain.value_objects.email import Email


class UserRepository(ABC):
    """
    Interface for user persistence operations.

    All methods define what needs to be done without prescribing how; the
    infrastructure layer provides concrete implementations.
    """

    @abstractmethod
    def save(self, user: User) -> User:
        """
        Persist a new or updated user.

        Args:
            user: User entity to save.

        Returns:
            The saved User.
        """
        ...

    @abstractmethod
    def find_by_email(self, email: Email) -> Optional[User]:
        """
        Find a user by their email address.

        Args:
            email: Email value object.

        Returns:
            User if found, otherwise None.
        """
        ...

    @abstractmethod
    def find_by_id(self, user_id: str) -> Optional[User]:
        """
        Find a user by their unique identifier.

        Args:
            user_id: UUID string of the user.

        Returns:
            User if found, otherwise None.
        """
        ...

    @abstractmethod
    def list_all(self, limit: int, offset: int = 0) -> List[User]:
        """
        Retrieve a paginated list of users.

        Args:
            limit: Maximum number of users to return.
            offset: Number of users to skip (for pagination).

        Returns:
            List of User entities.
        """
        ...

    @abstractmethod
    def delete(self, user_id: str) -> bool:
        """
        Permanently delete a user.

        Args:
            user_id: UUID string of the user to delete.

        Returns:
            True if the user was deleted, False if the user did not exist.
        """
        ...
