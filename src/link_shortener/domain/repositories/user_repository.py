from abc import ABC, abstractmethod
from datetime import datetime
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
    def count_active_with_permission(
        self, permission_name: str, excluding_user_id: Optional[str] = None
    ) -> int:
        """
        Count active users holding a permission through any of their roles.

        Exists so that "would this leave no administrator?" can be asked as
        one statement inside the transaction that answers it, rather than
        by listing every user and counting in Python.

        Args:
            permission_name: Permission to look for (e.g. ``"admin:all"``).
            excluding_user_id: User to leave out of the count -- the one the
                operation is about, whose privileges are about to change.

        Returns:
            Number of matching active users.
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

    @abstractmethod
    def delete_unverified_before(self, cutoff: datetime) -> int:
        """
        Delete accounts that were never confirmed and have run out of time.

        Without this an unconfirmed registration holds an address forever:
        the account exists, so registering that address again is refused,
        and nobody can sign in to it. Anyone could reserve an address they
        do not own, in bulk, and the owner would find it taken.

        Args:
            cutoff: Registrations older than this are removed.

        Returns:
            Number of accounts deleted.
        """
        ...
