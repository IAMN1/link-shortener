"""
Who may hand out which privileges, and what must never be handed away.

Two rules live here, both about administrators rather than about links.

The first is that nobody confers what they do not hold. Without it, any
role carrying ``admin:manage_users`` is a full administrator by a shorter
route: assign yourself the ``admin`` role and read the permissions back.
The same applies to ``admin:manage_roles``, which can put ``admin:all``
into a role the caller already wears. Both were reachable in one request.

This is settled ground elsewhere. Kubernetes enforces it in the API server
itself -- a subject cannot create or edit a Role granting more than it
holds -- and makes the exceptions explicit verbs (``escalate``, ``bind``)
rather than leaving them implicit. AWS IAM answers the same question with
permissions boundaries: a delegated administrator may create roles, but
never beyond the ceiling set for them. This module is that rule, and it is
the same shape as ``ANONYMOUS_PERMISSION_CEILING``, which bounds the other
end of the same spectrum.

A third rule, about which roles may be worn at all, lives in
``role_policy`` beside the name it turns on: it needs a role and not an
actor, and the entity that assembles a user has to be able to ask it.

The second rule is that the last administrator cannot be removed. It is
about availability, not privilege: an account that locks out the final
holder of ``admin:all`` leaves a system whose admin surface can only be
recovered from a shell.
"""

from typing import Iterable, Optional

from link_shortener.domain.entities.user import User
from link_shortener.domain.exceptions import DomainError
from link_shortener.domain.system_permissions import SystemPermissions
from link_shortener.domain.i18n import N_


def permissions_held_by(user: Optional[User]) -> frozenset:
    """
    Collect every permission name a user holds through their roles.

    Args:
        user: The user entity, or ``None`` for an anonymous caller.

    Returns:
        Frozen set of permission names; empty for ``None``.
    """
    if user is None:
        return frozenset()
    return frozenset(
        permission.name
        for role in user.roles
        for permission in role.permissions
    )


def is_superuser(user: Optional[User]) -> bool:
    """
    Report whether a user holds the unrestricted administrative permission.

    Args:
        user: The user entity, or ``None`` for an anonymous caller.

    Returns:
        ``True`` if the user holds ``admin:all``.
    """
    return user is not None and user.has_permission(
        SystemPermissions.ADMIN_ALL.value
    )


def require_may_confer(actor: Optional[User], permissions: Iterable[str]) -> None:
    """
    Check that an actor may hand out exactly these permissions.

    Args:
        actor: The user performing the operation.
        permissions: Permission names the operation would confer.

    Raises:
        DomainError: With code ``FORBIDDEN`` if any permission is one the
            actor does not hold. The message names the offending
            permissions: the caller is an administrator being told which
            grant exceeded their own authority, and withholding that turns
            a clear refusal into a puzzle.
    """
    if is_superuser(actor):
        return

    held = permissions_held_by(actor)
    exceeded = sorted(set(permissions) - held)
    if exceeded:
        raise DomainError(
                  "You cannot grant permissions you do not hold yourself: "
                  + ", ".join(exceeded),
                  code="FORBIDDEN",
                  template=N_(
                      "You cannot grant permissions you do not hold yourself: "
                      "%(permissions)s"
                  ),
                  params={"permissions": ", ".join(exceeded)},
              )


def require_not_last_administrator(remaining_administrators: int) -> None:
    """
    Refuse an operation that would leave the system without an administrator.

    Args:
        remaining_administrators: How many active holders of ``admin:all``
            would be left once the operation completed.

    Raises:
        DomainError: With code ``FORBIDDEN`` if none would be left.
    """
    if remaining_administrators <= 0:
        raise DomainError(
            N_("This would leave the system without an administrator"),
            code="FORBIDDEN",
        )
