from typing import List

from link_shortener.application import UnitOfWorkFactory, UserManagementService
from link_shortener.application.services.role_management_service import (
    RoleManagementService,
)
from link_shortener.domain import Role, RoleNotFoundError


def _roles_for(uow, role_names: List[str]) -> List[Role]:
    """
    Resolve role names for a command, adding the advice a shell can act on.

    The lookup is the service's, which is what keeps one answer to "no
    such role" across the API, the admin panel and these commands -- it
    was written out four times, twice here. What is added is the sentence
    that only makes sense at a shell: an operator who has not seeded yet
    meets this on their first command, and the fix is one line away.

    Args:
        uow: Active unit of work.
        role_names: Names as they were typed.

    Returns:
        The roles, in the order they were named.

    Raises:
        RuntimeError: If a name has no role behind it. A ``RuntimeError``
            rather than the domain error, because the CLI adapter turns
            one into a message and exit code 1, and a traceback is not an
            answer to a mistyped role.
    """
    try:
        return RoleManagementService.resolve_roles(uow, role_names)
    except RoleNotFoundError as absent:
        raise RuntimeError(
            f"{absent.message}. Please seed roles first "
            "(flask db load-base-roles)."
        ) from absent


def create_admin(
        uow_factory: UnitOfWorkFactory,
        user_service: UserManagementService,
        role_name: str,
        email: str,
        password: str
    ) -> str:
    """
    Create a new user with the specified role (typically 'admin').

    Args:
        uow_factory: Factory for Unit of Work instances.
        user_service: Service for user CRUD operations.
        role_name: Name of the role to assign (must exist in DB).
        email: User email.
        password: Plain-text password.

    Returns:
        Email of the newly created user.

    Raises:
        RuntimeError: If the specified role is not found.
        ValidationError, DomainError: Propagated from the service.
    """
    with uow_factory() as uow:
        user = user_service.create_user(
            uow=uow,
            email=email,
            password=password,
            roles=_roles_for(uow, [role_name]),
            is_active=True,
        )
        uow.commit()
    return user.email.value


def create_user(
        uow_factory: UnitOfWorkFactory,
        user_service: UserManagementService,
        email: str,
        password: str,
        role_names: List[str],
        is_active: bool = True,
    ) -> dict:
    """
    Create a new user with specified roles.

    Args:
        uow_factory: Factory for Unit of Work instances.
        user_service: Service for user CRUD operations.
        email: User email.
        password: Plain-text password.
        role_names: List of role names to assign.
        is_active: Whether the account is active.

    Returns:
        Dictionary with user details.

    Raises:
        RuntimeError: If a role is not found.
    """
    with uow_factory() as uow:
        roles = _roles_for(uow, role_names)

        user = user_service.create_user(
            uow=uow,
            email=email,
            password=password,
            roles=roles if roles else None,
            is_active=is_active,
        )
        uow.commit()
    return {"email": user.email.value, "is_active": user.is_active}
