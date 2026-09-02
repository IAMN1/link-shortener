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

The second rule is the first one read backwards: nobody acts on an account
that holds *authority* they do not. Conferring and taking away are the same
power seen from two sides, and only the conferring half was guarded -- so a
role carrying ``admin:manage_users`` and nothing else could delete or
deactivate an ``auditor``, or strip its roles, none of which "grants"
anything and none of which was therefore checked. Kubernetes draws the line
in the same place: ``escalate`` is a verb because raising somebody else's
privileges is a distinct authority, and so is reaching an account whose
privileges exceed your own.

Authority, and not simply "more". Written as a plain set difference the
rule refuses the ordinary work the role exists for: an account that merely
signed up holds ``link:view_own`` and ``link:delete_own``, which an
administrative role has no reason to carry, so *every* account would have
looked like a superior. ``is_privileged`` draws the line the rule needs.

The third rule is that the last administrator cannot be removed. It is
about availability, not privilege: an account that locks out the final
holder of ``admin:all`` leaves a system whose admin surface can only be
recovered from a shell.
"""

from typing import Iterable, Optional

from link_shortener.domain.entities.user import User
from link_shortener.domain.exceptions import (
    DomainError, PermissionDeniedError,
)
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
        PermissionDeniedError: If any permission is one the actor does not
            hold. It carries them in ``exceeded``, and the message names
            them as well: the caller is an administrator being told which
            grant went past their own authority, and withholding that
            turns a clear refusal into a puzzle.
    """
    if is_superuser(actor):
        return

    held = permissions_held_by(actor)
    exceeded = sorted(set(permissions) - held)
    if exceeded:
        # ``exceeded`` rather than ``required``: what is missing here is
        # not one permission the caller needs but the set they tried to
        # hand out without holding it, which is an escalation attempt and
        # reads differently in the journal.
        raise PermissionDeniedError(
            "You cannot grant permissions you do not hold yourself: "
            + ", ".join(exceeded),
            exceeded=exceeded,
            template=N_(
                "You cannot grant permissions you do not hold yourself: "
                "%(permissions)s"
            ),
            params={"permissions": ", ".join(exceeded)},
        )


#: Resources whose every permission is authority over the service rather
#: than use of it.
PRIVILEGED_RESOURCES = frozenset({"admin", "audit", "logs"})

#: The suffix that marks a permission reaching past its holder's own rows.
#: ``link:delete_own`` is use; ``link:delete_any`` is authority.
REACHES_ANOTHERS_SUFFIX = "_any"


def is_privileged(permission: str) -> bool:
    """
    Report whether a permission is authority rather than use.

    A rule and not a list, for the reason ``tests/conftest.py`` gives about
    its own allowlist: an enumeration covers what existed when it was
    written, and the next permission added is the one it misses. Here the
    miss would be silent and in the direction that matters -- a new
    administrative permission nobody classified would leave the accounts
    holding it reachable by anyone who may manage users.

    Two shapes count, and between them they decide every permission this
    service defines -- ten of the fifteen match one of them and the five
    named below match neither, which is the answer for those, not a gap.
    Everything under ``admin``, ``audit`` and ``logs`` is
    authority by the resource it names. Everything ending in ``_any`` is
    authority by reaching past its holder's own rows --
    ``link:delete_own`` is use, ``link:delete_any`` is not.

    What is deliberately *not* privileged: ``link:create``,
    ``link:view_own``, ``link:delete_own``, ``stats:view_basic`` and
    ``stats:view_full``. The first four are what an account that merely
    signed up holds, and the last is a service-wide aggregate rather than
    a reach into anybody's account.

    Args:
        permission: A permission name in ``resource:action`` form.

    Returns:
        ``True`` if holding it makes an account somebody's superior.
    """
    resource, _, action = permission.partition(":")

    return resource in PRIVILEGED_RESOURCES or action.endswith(
        REACHES_ANOTHERS_SUFFIX
    )


def require_may_act_on(actor: Optional[User], target: Optional[User]) -> None:
    """
    Check that an actor may act on an account at all.

    The mirror of ``require_may_confer``. That one asks whether the actor
    may hand a permission out; this one asks whether they may reach an
    account that already holds one they do not. Deleting, deactivating and
    re-roling all take privileges away rather than give them, so none of
    them passed through the conferring check -- and taking ``audit:view``
    off the only account that has it is as much an act of privilege as
    granting it.

    Only privileged permissions are compared -- see ``is_privileged``. The
    ordinary ones an account gets by signing up are not authority, and
    counting them would make every account a superior of every purely
    administrative role.

    Self is always allowed: the difference between what the target holds
    and what the actor holds is empty when they are the same account, so
    an administrator may still deactivate themselves and meet the
    last-administrator rule rather than this one.

    Args:
        actor: The user performing the operation.
        target: The account being acted upon, or ``None`` when there is
            none -- an id that names nobody is the use case's answer to
            give, not this rule's.

    Raises:
        PermissionDeniedError: If the target holds any permission the
            actor does not. It carries them in ``exceeded``, the same
            field ``require_may_confer`` uses, because the journal reads
            them as one kind of event: an authority reached past.
    """
    if is_superuser(actor):
        return

    if target is None:
        return

    held_by_actor = permissions_held_by(actor)
    exceeded = sorted(
        permission
        for permission in permissions_held_by(target)
        if is_privileged(permission) and permission not in held_by_actor
    )
    if exceeded:
        raise PermissionDeniedError(
            "You cannot act on an account holding permissions you do not "
            "hold yourself: " + ", ".join(exceeded),
            exceeded=exceeded,
            template=N_(
                "You cannot act on an account holding permissions you do "
                "not hold yourself: %(permissions)s"
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
