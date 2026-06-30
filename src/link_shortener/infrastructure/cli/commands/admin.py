from typing import Callable, List, Optional

from link_shortener.application import UnitOfWork, UserManagementService, RequestContext
from link_shortener.application.ports.logger.logger import Logger


def create_admin(
        uow_factory: Callable[[], UnitOfWork],
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
        role = uow.roles.get_by_name(role_name)
        if not role:
            raise RuntimeError(
                f"Role '{role_name}' not found. Please seed roles first "
                "(flask db load-base-roles)."
            )
        user = user_service.create_user(
            uow=uow,
            email=email,
            password=password,
            roles=[role],
            is_active=True,
        )
        uow.commit()
    return user.email.value


def create_user(
        uow_factory: Callable[[], UnitOfWork],
        user_service: UserManagementService,
        logger: Logger,
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
        logger: Logger instance.
        email: User email.
        password: Plain-text password.
        role_names: List of role names to assign.
        is_active: Whether the account is active.

    Returns:
        Dictionary with user details.

    Raises:
        RuntimeError: If a role is not found.
    """
    context = RequestContext(request_id="cli-create-user")
    with uow_factory() as uow:
        roles = []
        for name in role_names:
            role = uow.roles.get_by_name(name)
            if not role:
                raise RuntimeError(
                    f"Role '{name}' not found. Please seed roles first "
                    "(flask db load-base-roles)."
                )
            roles.append(role)

        user = user_service.create_user(
            uow=uow,
            email=email,
            password=password,
            roles=roles if roles else None,
            is_active=is_active,
        )
        uow.commit()
    return {"email": user.email.value, "is_active": user.is_active}
