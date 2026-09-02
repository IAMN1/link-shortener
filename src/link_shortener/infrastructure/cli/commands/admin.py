from typing import List

from link_shortener.application import UnitOfWorkFactory, UserManagementService
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.services.role_management_service import (
    RoleManagementService,
)
from link_shortener.domain import Role, RoleNotFoundError, User


def _roles_for(uow: UnitOfWork, role_names: List[str]) -> List[Role]:
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


def create_user(
        uow_factory: UnitOfWorkFactory,
        user_service: UserManagementService,
        audit: AuditLogger,
        email: str,
        password: str,
        role_names: List[str],
    ) -> User:
    """
    Create a new account with the named roles, and record that it happened.

    The one function behind both commands. ``create-admin`` and
    ``create-user`` were the same twenty lines twice, differing in the
    shape of what they handed back and in whether the role arrived as a
    name or as a list of one -- so a rule added to either was a rule the
    other went on without. The account itself comes back whole rather
    than as a string or a dictionary: the caller prints two of its fields
    and both are already named and typed on the entity.

    The record is written for the reason ``CreateUserUseCase`` writes it
    on the HTTP path: creating an account is handing out entitlements,
    and an administrator who appeared without one is the first thing an
    investigation looks for. These commands wrote nothing at all, so the
    account an operator seeds a deployment with -- typically the only
    administrator it has -- was the one account whose creation the
    journal did not hold.

    Written after the commit and outside the unit of work: a journal that
    cannot be written is not a reason to refuse an account that has
    already been created and committed.

    No escalation check, unlike ``CreateUserUseCase``, which asks
    ``require_may_grant_roles`` before handing a role out. That rule
    stops an administrator conferring permissions they do not themselves
    hold; there is nobody to hold anything here. A command at a shell
    runs with the database credentials and the configuration in hand,
    which is strictly more than any role confers -- the same reasoning
    ``delete_link`` gives for not enforcing ownership. What the roles
    themselves may be is still checked, by ``User.create``, because that
    is a rule about the account and not about who is asking.

    Args:
        uow_factory: Factory for Unit of Work instances.
        user_service: Service for user CRUD operations.
        audit: Where the creation is recorded, already carrying the
            command's context.
        email: User email.
        password: Plain-text password.
        role_names: Names of the roles to assign.

    Returns:
        The account that was created.

    Raises:
        RuntimeError: If a name has no role behind it.
        ValidationError, DomainError: Propagated from the service.
    """
    with uow_factory() as uow:
        user = user_service.create_user(
            uow=uow,
            email=email,
            password=password,
            roles=_roles_for(uow, role_names),
            # Active, always: an account an operator creates at a shell
            # and cannot then sign in to is a broken tool. This was a
            # parameter defaulting to True that no caller ever set, which
            # reads as a choice being offered and is not one.
            is_active=True,
        )
        uow.commit()

    # The roles are read off the account rather than off ``role_names``,
    # as on the HTTP path and for the reason given there: asked for none,
    # the account is given the default one, and a record repeating the
    # empty request would say it was created with no entitlements at all.
    audit.log_user_created(
        target_user_id=user.id,
        email=user.email.value,
        roles=[role.name for role in user.roles],
    )
    return user
