from abc import ABC, abstractmethod
from typing import Optional

from link_shortener.domain import User


class AuthorizationService(ABC):
    """
    Abstract service for permission checking (RBAC).

    Implementations determine whether a user has a given permission
    based on their assigned roles.
    """

    @abstractmethod
    def is_allowed(
        self,
        user: Optional[User],
        permission: str,
    ) -> bool:
        """
        Check if a user holds a specific permission.

        Args:
            user: The user (may be None for anonymous).
            permission: Permission name string (e.g., 'link:create').

        Returns:
            True if access is permitted.
        """
        ...
