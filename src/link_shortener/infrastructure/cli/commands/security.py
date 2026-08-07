import secrets
import os
from typing import Optional, Callable
from link_shortener.application import UnitOfWork
from link_shortener.domain import Email


def validate_token(
    auth_service,  # AuthenticationService
    token: str
) -> dict:
    """Validate a JWT token and return its claims."""
    try:
        claims = auth_service.validate_token(token)
        if not claims:
            # validate_token returns None for an invalid or expired token
            # instead of raising, so this case has to be handled explicitly.
            return {
                "valid": False,
                "error": "Token is invalid or expired",
            }
        return {
            "valid": True,
            # The user id lives in the standard "sub" claim, not "user_id" -
            # see JwtAuthenticationService._create_token.
            "user_id": claims.get("sub"),
            "email": claims.get("email"),
            "roles": claims.get("roles", []),
            "type": claims.get("type"),
            "exp": claims.get("exp"),
        }
    except Exception as e:
        return {
            "valid": False,
            "error": str(e),
        }


def generate_secrets() -> dict[str, str]:
    """Generate new secure random values for SECRET_KEY and SHORT_CODE_PEPPER."""
    return {
        "SECRET_KEY": secrets.token_hex(32),
        "SHORT_CODE_PEPPER": secrets.token_hex(32),
    }


def check_secrets() -> dict[str, bool]:
    """Check if required secrets are configured in environment."""
    return {
        "SECRET_KEY": bool(os.environ.get("SECRET_KEY")),
        "SHORT_CODE_PEPPER": bool(os.environ.get("SHORT_CODE_PEPPER")),
    }


def list_users(uow_factory: Callable[[], UnitOfWork]) -> list[dict]:
    """List all users with their roles."""
    with uow_factory() as uow:
        users = uow.users.list_all()
        return [
            {
                "id": str(user.id),
                "email": user.email.value,
                "is_active": user.is_active,
                "roles": [role.name for role in user.roles],
            }
            for user in users
        ]


def list_roles(uow_factory: Callable[[], UnitOfWork]) -> list[dict]:
    """List all roles with their permissions."""
    with uow_factory() as uow:
        roles = uow.roles.list_all()
        return [
            {
                "id": str(role.id),
                "name": role.name,
                "description": role.description,
                "permissions": [perm.name for perm in role.permissions],
            }
            for role in roles
        ]


def reset_password(
    uow_factory: Callable[[], UnitOfWork],
    user_service,  # UserManagementService
    email: str,
    new_password: str
) -> bool:
    """Reset a user's password."""
    with uow_factory() as uow:
        user = uow.users.find_by_email(Email(email))
        if not user:
            return False
        user_service.update_password(uow, user, new_password)
        uow.commit()
        return True
