"""
Applying the privilege rules to the administrative use cases.

The rules themselves are in ``domain/policies/privilege_policy.py``. What
lives here is the part that needs a Unit of Work: reading the actor and
counting administrators from the same transaction the operation runs in,
rather than from the request context, which carries role names only and was
assembled before the operation began.
"""

from typing import Iterable, Optional

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
    # Before the count, in the transaction that will write the change:
    # without it two administrators demoting each other both read "one
    # other would remain" and both proceed.
    uow.users.lock_administrator_set()
    remaining = uow.users.count_active_with_permission(
        SystemPermissions.ADMIN_ALL.value, excluding_user_id=user_id
    )
    require_not_last_administrator(remaining)


def require_administrator_survives_without(uow: UnitOfWork, role: Role) -> None:
    """
    Refuse an operation that takes ``admin:all`` off the last administrator.

    The rule was on the three routes that act on an account -- re-roling,
    deleting, deactivating -- and on neither of the two that act on a
    role. Both reach the same end, and both were measured against the
    running stack: an administrator whose ``admin:all`` came through a
    role of their own making, then ``PUT /admin/roles/<name>/permissions``
    without it (200) or ``DELETE /admin/roles/<name>`` (200), and the
    admin API answered 403 to everybody afterwards. The deletion left
    the account with no roles at all.

    Counted excluding this role, so an administrator who also holds
    ``admin:all`` through another one keeps the operation allowed.

    Args:
        uow: Active Unit of Work.
        role: The role about to stop granting what it grants.

    Raises:
        DomainError: With code ``FORBIDDEN`` if nobody would be left.
    """
    # Nothing to protect if this role is not what makes an administrator.
    if not role.has_permission(SystemPermissions.ADMIN_ALL.value):
        return

    uow.users.lock_administrator_set()
    remaining = uow.users.count_active_with_permission(
        SystemPermissions.ADMIN_ALL.value, excluding_role_id=role.id
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
