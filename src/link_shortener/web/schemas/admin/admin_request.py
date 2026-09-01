from typing import List, Optional
from pydantic import ConfigDict, Field

from link_shortener.web.schemas.strict import (
    A_PASSWORD,
    AN_ADDRESS,
    StrictRequest,
)

from link_shortener.domain.policies.password_policy import MIN_PASSWORD_LENGTH
from link_shortener.domain.policies.role_policy import (
    ROLE_DESCRIPTION_MAX_LENGTH, ROLE_NAME_MAX_LENGTH, ROLE_NAME_MIN_LENGTH,
    ROLE_NAME_PATTERN,
)
from link_shortener.domain.value_objects.email import EMAIL_PATTERN


class CreateUserRequest(StrictRequest):
    """Request schema for creating a new user."""
    email: str = Field(
        ...,
        pattern=EMAIL_PATTERN,
        description="User Email",
        # What the document says an address is, from the one place that
        # says it: a reader of this operation learns what a reader of
        # sign-in does, and a client generator that understands `format`
        # gets the hint here too. `pattern` is in it as well, the same
        # expression this field validates with.
        json_schema_extra=AN_ADDRESS,
    )
    """The shape comes from the value object every path builds afterwards.

    It was the same expression written out a second time, which is the
    arrangement ``password`` and ``name`` were both taken out of: a copy
    disagrees silently, and here it would disagree by refusing at the
    schema what the domain accepts, or -- the direction that costs
    something -- accepting at the schema what the domain then refuses with
    a 400 naming no field the caller sent.
    """
    password: str = Field(
        ...,
        min_length=MIN_PASSWORD_LENGTH,
        # The length the document states, from the one place that states
        # it. The ceiling is in the document only and not as a second
        # gate: the policy already refuses a longer password, and a schema
        # that refused it first would answer with Pydantic's sentence
        # where every other password rule answers with the policy's.
        json_schema_extra=A_PASSWORD,
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


class UpdateUserRolesRequest(StrictRequest):
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


class CreateRoleRequest(StrictRequest):
    """Request schema for creating a new role."""
    name: str = Field(
        ...,
        min_length=ROLE_NAME_MIN_LENGTH,
        max_length=ROLE_NAME_MAX_LENGTH,
        pattern=ROLE_NAME_PATTERN,
        description="Unique role name"
    )
    """The shape comes from the domain policy rather than from numbers
    typed here, for the reason ``CreateUserRequest.password`` gives: a
    contract that disagrees with what the rest of the system accepts is
    the shape a hole arrives in later. Length alone was the whole rule,
    and it let through names the route that deletes a role cannot
    address -- see ``role_policy``.
    """
    description: Optional[str] = Field(
        "",
        max_length=ROLE_DESCRIPTION_MAX_LENGTH,
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


class UpdateRolePermissionsRequest(StrictRequest):
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
