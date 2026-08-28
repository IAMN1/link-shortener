from typing import List, Optional
from pydantic import BaseModel, ConfigDict, field_serializer
from datetime import datetime

class PermissionResponseSchema(BaseModel):
    """
    Schema for returning permission data in API responses.

    Attributes:
        id: Unique permission identifier.
        name: Permission name (resource:action).
        resource: Target resource.
        action: Allowed action.
        description: Optional human-readable explanation.
    """
    id: str
    name: str
    resource: str
    action: str
    description: Optional[str] = None

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "perm-123",
                "name": "link:create",
                "resource": "link",
                "action": "create",
                "description": "Create a new short link"
            }
        }
    )

    @classmethod
    def from_dto(cls, permission) -> "PermissionResponseSchema":
        """
        Create a schema instance from a permission DTO.

        Args:
            permission: DTO with ``id``, ``name``, ``resource``, ``action``,
                ``description`` attributes.

        Returns:
            PermissionResponseSchema instance.
        """
        return cls(
            id=permission.id,
            name=permission.name,
            resource=permission.resource,
            action=permission.action,
            description=permission.description,
        )

class RoleResponseSchema(BaseModel):
    """
    Schema for returning role data, including its permissions.

    Attributes:
        id: Unique role identifier.
        name: Role name.
        description: Optional description.
        is_system: Whether it is a protected system role.
        permissions: List of permissions assigned to the role.
    """
    id: str
    name: str
    description: Optional[str] = None
    is_system: bool
    permissions: List[PermissionResponseSchema]

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "role-456",
                "name": "editor",
                "description": "A role for content editors",
                "is_system": False,
                "permissions": [
                    {
                        "id": "perm-123",
                        "name": "link:create",
                        "resource": "link",
                        "action": "create"
                    }
                ]
            }
        }
    )

    @classmethod
    def from_dto(cls, role) -> "RoleResponseSchema":
        """
        Create a schema instance from a role DTO.

        Args:
            role: DTO with ``id``, ``name``, ``description``, ``is_system``,
                and ``permissions`` (list of permission DTOs).

        Returns:
            RoleResponseSchema instance.
        """
        return cls(
            id=role.id,
            name=role.name,
            description=role.description,
            is_system=role.is_system,
            permissions=[
                PermissionResponseSchema.from_dto(p)
                for p in role.permissions
            ],
        )

class UserResponseSchema(BaseModel):
    """
    Schema for returning user data in API responses.

    Attributes:
        id: Unique user identifier.
        email: User's email address.
        roles: List of assigned role names.
        is_active: Whether an administrator has left the account enabled.
        email_verified: Whether the owner has proved the address is theirs.
            Signing in needs both this and ``is_active``; an operator
            reading only the latter cannot tell why an "Active" account
            gets refused at the login form.
        created_at: Registration timestamp.
        last_login: Last login timestamp (if any).
    """
    id: str
    email: str
    roles: List[str]
    is_active: bool
    email_verified: bool
    created_at: datetime
    last_login: Optional[datetime] = None

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "user-789",
                "email": "user@example.com",
                "roles": ["editor", "viewer"],
                "is_active": True,
                "email_verified": True,
                "created_at": "2026-01-15T10:30:00",
                "last_login": "2026-02-20T15:30:00"
            }
        }
    )

    @field_serializer('created_at', 'last_login')
    def serialize_datetime(self, value: Optional[datetime]) -> Optional[str]:
        """
        Serialize datetime fields to ISO 8601 strings.

        Args:
            value: A timezone-aware datetime or ``None``.

        Returns:
            ISO-formatted string or ``None``.
        """
        if value is None:
            return None
        return value.isoformat()

    @classmethod
    def from_dto(cls, user) -> "UserResponseSchema":
        """
        Create a schema instance from a user DTO.

        Args:
            user: DTO with ``id``, ``email``, ``roles``, ``is_active``,
                ``created_at``, and optional ``last_login``.

        Returns:
            UserResponseSchema instance.
        """
        return cls(
            id=user.id,
            email=user.email,
            roles=user.roles,
            is_active=user.is_active,
            email_verified=user.email_verified,
            created_at=user.created_at,
            last_login=user.last_login,
        )
