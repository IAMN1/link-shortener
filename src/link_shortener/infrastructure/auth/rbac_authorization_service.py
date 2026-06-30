from typing import Optional

from link_shortener.application import AuthorizationService
from link_shortener.domain import User


class RBACAuthorizationService(AuthorizationService):
    """
    Determines if a user has a given permission based on assigned roles.

    Users holding the ``admin:all`` permission are considered super-users
    and are granted implicit access to everything.
    """

    def is_allowed(
        self,
        user: Optional[User],
        permission: str,
    ) -> bool:
        """
        Check if a user is allowed to perform an action.

        Args:
            user: The user entity (``None`` for anonymous).
            permission: Permission string (e.g., ``"link:create"``).

        Returns:
            ``True`` if the user has the permission or is a super-admin.
        """
        if user is None:
            return False
        # Admins bypass all permission checks.
        if user.has_permission("admin:all"):
            return True
        # Standard role-based check.
        return user.has_permission(permission)
