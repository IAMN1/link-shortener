from typing import Callable

from link_shortener.application import UnitOfWork, UserManagementService


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
