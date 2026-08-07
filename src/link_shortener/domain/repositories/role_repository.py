from abc import ABC, abstractmethod
from typing import List, Optional

from link_shortener.domain.entities.role import Role


class RoleRepository(ABC):
    """Interface for role persistence operations."""

    @abstractmethod
    def get_by_name(self, name: str) -> Optional[Role]:
        """
        Find a role by its unique name.

        Args:
            name: Role name (e.g., ``"admin"``).

        Returns:
            Role entity if found, otherwise None.
        """
        ...

    @abstractmethod
    def save(self, role: Role) -> Role:
        """
        Persist a new or updated role.

        Args:
            role: The Role entity to save.

        Returns:
            The saved Role (may reflect database‑generated values).
        """
        ...

    @abstractmethod
    def delete(self, role_id: str) -> None:
        """
        Permanently delete a role by its identifier.

        Args:
            role_id: The UUID string of the role to delete.
        """
        ...

    @abstractmethod
    def list_all(self) -> List[Role]:
        """
        Retrieve all roles.

        Returns:
            List of all Role entities in the system.
        """
        ...
