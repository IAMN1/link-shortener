"""
Applying the privilege rules to the administrative use cases.

The rules themselves are in ``domain/policies/privilege_policy.py``. What
lives here is the part that needs a Unit of Work: reading the actor and
counting administrators from the same transaction the operation runs in,
rather than from the request context, which carries role names only and was
assembled before the operation began.
"""

from typing import Iterable, List, Optional

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.domain import Role, SystemPermissions, User
from link_shortener.domain.policies.privilege_policy import (
    require_may_confer,
    require_not_last_administrator,
)


def load_actor(context: RequestContext, uow: UnitOfWork) -> Optional[User]:
    """
    Load the user an administrative request is acting as.

    Args:
        context: Request context carrying the authenticated user's id.
        uow: Active Unit of Work.

    Returns:
        The ``User`` entity, or ``None`` for an unauthenticated request.
    """
    if context.current_user is None:
        return None
    return uow.users.find_by_id(context.current_user.id)


def require_may_grant_roles(
    context: RequestContext, uow: UnitOfWork, roles: Iterable[Role]
) -> None:
    """
    Check that the actor may hand out every permission in these roles.

    Args:
        context: Request context with the actor's identity.
        uow: Active Unit of Work.
        roles: Roles about to be assigned to somebody.

    Raises:
        DomainError: With code ``FORBIDDEN`` if any role carries a
            permission the actor does not hold.
    """
    conferred = [
        permission.name for role in roles for permission in role.permissions
    ]
    require_may_confer(load_actor(context, uow), conferred)


def require_may_grant_permissions(
    context: RequestContext, uow: UnitOfWork, permission_names: Iterable[str]
) -> None:
    """
    Check that the actor may put these permissions into a role.

    Args:
        context: Request context with the actor's identity.
        uow: Active Unit of Work.
        permission_names: Permissions about to be written into a role.

    Raises:
        DomainError: With code ``FORBIDDEN`` if the actor holds fewer.
    """
    require_may_confer(load_actor(context, uow), permission_names)


def require_administrator_remains(uow: UnitOfWork, user_id: str) -> None:
    """
    Refuse an operation that would strip the system of its last admin.

    Counted excluding the user the operation is about, because that user is
    the one whose privileges or account are about to go away.

    Args:
        uow: Active Unit of Work.
        user_id: The user being deleted, deactivated, or re-roled.

    Raises:
        DomainError: With code ``FORBIDDEN`` if nobody else would be left.
    """
    remaining = uow.users.count_active_with_permission(
        SystemPermissions.ADMIN_ALL.value, excluding_user_id=user_id
    )
    require_not_last_administrator(remaining)


def would_keep_admin(roles: Iterable[Role]) -> bool:
    """
    Report whether a set of roles still confers ``admin:all``.

    Args:
        roles: The roles a user would hold after the operation.

    Returns:
        ``True`` if at least one of them grants ``admin:all``.
    """
    return any(
        permission.name == SystemPermissions.ADMIN_ALL.value
        for role in roles
        for permission in role.permissions
    )


def is_administrator(uow: UnitOfWork, user_id: str) -> bool:
    """
    Report whether a stored user currently holds ``admin:all``.

    Args:
        uow: Active Unit of Work.
        user_id: User to inspect.

    Returns:
        ``True`` if the user exists and holds the permission.
    """
    user = uow.users.find_by_id(user_id)
    return user is not None and user.has_permission(
        SystemPermissions.ADMIN_ALL.value
    )
