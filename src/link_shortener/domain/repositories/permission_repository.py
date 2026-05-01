from abc import ABC, abstractmethod
from typing import List

from link_shortener.domain.entities.permission import Permission

class PermissionRepository(ABC):
    """Interface for permission persistence operations."""
    @abstractmethod
    def get_by_names(self, names: List[str]) -> List[Permission]:
        """
        Retrieve permissions by their unique names.

        Args:
            names: List of permission names (e.g., ``["link:create", "admin:all"]``).

        Returns:
            List of Permission entities matching the given names. If a name is not
            found, it is silently omitted from the result.
        """
        ...
