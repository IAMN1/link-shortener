from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional
import uuid

from link_shortener.domain.entities.role import Role
from link_shortener.domain.value_objects.email import Email
from link_shortener.domain.value_objects.password_hash import PasswordHash



@dataclass
class User:
    """
    User aggregate root.

    Encapsulates identity, authentication credentials, and role-based access
    control. Business rules such as permission checking, activation, and
    deactivation live here.

    Attributes:
        id: Unique identifier (UUID string).
        email: User's email value object.
        password_hash: Hashed password value object.
        roles: List of Role entities assigned to the user.
        is_active: Flag indicating whether the user account is active.
        created_at: Account creation timestamp.
        last_login: Timestamp of the last successful login (if any).
    """
    id: str
    email: Email
    password_hash: PasswordHash
    roles: List[Role] = field(default_factory=list)
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_login: Optional[datetime] = None

    @classmethod
    def create(
        cls, email: Email, password_hash: PasswordHash, roles: Optional[List[Role]] = None
    ) -> "User":
        """
        Factory method to create a new User.

        Generates a UUID identifier and initialises mandatory fields.

        Args:
            email: Validated email value object.
            password_hash: Hashed password value object.
            roles: Optional list of Role entities to assign; defaults to an empty list.

        Returns:
            A new User instance with ``is_active=True`` and ``created_at`` set to now.
        """
        return cls(
            id=str(uuid.uuid4()),
            email=email,
            password_hash=password_hash,
            roles=roles or [],
        )
    
    def has_permission(self, permission_name: str) -> bool:
        """
        Check whether the user possesses a specific permission.

        A user has a permission if at least one of their assigned roles grants it.

        Args:
            permission_name: The permission name to check (e.g., ``"link:create"``).

        Returns:
            True if any of the user's roles contain the given permission.
        """
        return any(role.has_permission(permission_name) for role in self.roles)
    
    def is_admin(self) -> bool:
        """
        Convenience method to check if the user has full administrative privileges.

        Returns:
            True if the ``"admin:all"`` permission is granted.
        """
        return self.has_permission("admin:all")
    
    def activate(self) -> None:
        """Activate a previously deactivated user account."""
        self.is_active = True
    
    def deactivate(self) -> None:
        """Deactivate the user account (soft delete)."""
        self.is_active = False
