from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field

from link_shortener.domain.policies.password_policy import MIN_PASSWORD_LENGTH


class CreateUserRequest(BaseModel):
    """Request schema for creating a new user."""
    email: str = Field(
        ..., 
        pattern=r"^[^@]+@[^@]+\.[^@]+$", 
        description="User Email"
    )
    password: str = Field(
        ...,
        min_length=MIN_PASSWORD_LENGTH,
        description=(
            f"User password (min {MIN_PASSWORD_LENGTH} characters, and not "
            f"one attackers already have)"
        ),
    )
    """The floor comes from the domain policy rather than a number typed
    here. It said six while the policy enforced eight, so the schema
    promised a password the service would refuse -- and an operator or a
    generated client reading it would have believed the schema. Nothing
    could actually be set weaker, because the check lives in the hashing
    every path goes through, but a contract that disagrees with the code is
    the shape a hole arrives in later.
    """
    is_active: bool = Field(
        True, 
        description="Whether the account is active"
    )
    roles: Optional[List[str]] = Field(
        None, 
        description="Optional list of role names; if missing the default role is used"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "newuser@example.com",
                "password": "a-password-of-their-own",
                "is_active": True,
                "roles": ["user", "editor"]
            }
        }
    )


class UpdateUserRolesRequest(BaseModel):
    """Request schema for replacing a user's roles."""
    roles: List[str] = Field(
        ..., 
        min_length=1, 
        description="New list of role names"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "roles": ["user", "analyst"]
            }
        }
    )


class CreateRoleRequest(BaseModel):
    """Request schema for creating a new role."""
    name: str = Field(
        ..., 
        min_length=2, 
        description="Unique role name"
    )
    description: Optional[str] = Field(
        "", 
        description="Human-readable description"
    )
    permissions: List[str] = Field(
        ..., 
        min_length=1, 
        description="List of permission names"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "editor",
                "description": "Role for content managers",
                "permissions": ["link:create", "link:view_own", "stats:view_basic"]
            }
        }
    )


class UpdateRolePermissionsRequest(BaseModel):
    """Request schema for updating role permissions (full replacement)."""
    permissions: List[str] = Field(
        ..., 
        min_length=1, 
        description="New list of permission names"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "permissions": ["link:create", "link:delete_own"]
            }
        }
    )
