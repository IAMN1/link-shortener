from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional
import uuid

from link_shortener.domain.entities.role import Role
from link_shortener.domain.policies.role_policy import (
    require_roles_are_assignable,
)
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
        email_verified: Whether the address has been proven to be readable
            by whoever registered it. Separate from ``is_active``, which is
            an administrator's decision about an account that already
            exists; this one is the account's own unfinished business.
        created_at: Account creation timestamp.
        last_login: Timestamp of the last successful login (if any).
    """
    id: str
    email: Email
    password_hash: PasswordHash
    roles: List[Role] = field(default_factory=list)
    is_active: bool = True
    email_verified: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_login: Optional[datetime] = None

    @classmethod
    def create(
        cls,
        email: Email,
        password_hash: PasswordHash,
        roles: Optional[List[Role]] = None,
        email_verified: bool = False,
    ) -> "User":
        """
        Factory method to create a new User.

        Generates a UUID identifier and initialises mandatory fields.

        Args:
            email: Validated email value object.
            password_hash: Hashed password value object.
            roles: Optional list of Role entities to assign; defaults to an empty list.
            email_verified: Whether the address counts as already proven.
                False for self-registration, which is the whole point of
                the confirmation. True where an administrator created the
                account and vouches for the address: nobody is going to
                mail that person a link, and an account created by an
                administrator that then cannot sign in is a broken tool.

        Returns:
            A new User instance with ``is_active=True`` and ``created_at`` set to now.

        Raises:
            RoleNotAssignableError: If one of the roles is one no account
                may wear.
        """
        # Asked here because this is where a user first gets roles, and
        # registration builds the entity directly rather than through
        # ``UserManagementService``: the rule lived in that service alone
        # and registration walked past it.
        require_roles_are_assignable(roles or [])

        return cls(
            id=str(uuid.uuid4()),
            email=email,
            password_hash=password_hash,
            roles=roles or [],
            email_verified=email_verified,
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

    def __eq__(self, other: object) -> bool:
        """Equality based on user ID."""
        if not isinstance(other, User):
            return False
        return self.id == other.id

    def __hash__(self) -> int:
        """Hash based on user ID."""
        return hash(self.id)

    def activate(self) -> None:
        """Activate a previously deactivated user account."""
        self.is_active = True

    def deactivate(self) -> None:
        """Deactivate the user account (soft delete)."""
        self.is_active = False

    def confirm_email(self) -> None:
        """Record that the address was proven readable by its owner."""
        self.email_verified = True
