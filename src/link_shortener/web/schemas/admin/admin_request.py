from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class CreateUserRequest(BaseModel):
    """Request schema for creating a new user."""
    email: str = Field(
        ..., 
        pattern=r"^[^@]+@[^@]+\.[^@]+$", 
        description="User Email"
    )
    password: str = Field(
        ..., 
        min_length=6, 
        description="User password (min 6 symbols)"
    )
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
                "password": "securePassword123",
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
