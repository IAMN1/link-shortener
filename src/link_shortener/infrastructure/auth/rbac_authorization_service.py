"""
Role-based authorization, including the permissions of anonymous callers.

An unauthenticated request is not a user without roles -- it is the
``guest`` role. That role lives in the database like any other, so it can
be inspected and adjusted by an operator. What it can never do is exceed
``ANONYMOUS_PERMISSION_CEILING``.
"""

from typing import Callable, Optional

from link_shortener.application import AuthorizationService
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.domain import SystemPermissions, User
from link_shortener.domain.policies.role_policy import GUEST_ROLE_NAME

# ==============================================================================
# Anonymous access
# ==============================================================================

ANONYMOUS_PERMISSION_CEILING = frozenset({
    SystemPermissions.STATS_VIEW_BASIC.value,
    SystemPermissions.LINK_CREATE.value,
})
"""
Everything an unauthenticated caller is capable of holding, whatever the
stored ``guest`` role happens to say.

The role is read from the database, so what it grants is runtime state, and
runtime state is reachable. On a normally seeded deployment ``guest`` carries
``is_system: true`` and the admin API refuses to touch it -- but that flag is
itself runtime state, and it is not hard to end up without it: ``create_role``
hard-codes ``is_system=False``, and seeding only rewrites scalar fields when
asked to, so a ``guest`` row that was deleted and recreated through the API
stays unprotected for good. From there
``PUT /admin/roles/guest/permissions`` writes whatever it likes.

That is the narrow path. The reason to block it in code rather than patch the
path is that the same class of mistake has been made at every scale:
Kubernetes treats ``system:unauthenticated`` as an ordinary RoleBinding
subject, the *RBAC Buster* campaign wrote its own policies through anonymous
access, and GKE 1.28 answered by refusing, in code, to bind ``cluster-admin``
to ``system:anonymous``. The platform stopped relying on the administrator
not to do it. PostgreSQL told the same story with ``PUBLIC`` and
CVE-2018-1058. The ceiling is that measure, one size down.

Grants outside this set are dropped rather than rejected on write: the check
belongs where the permission is used, so a set widened later cannot leave an
unguarded path behind.
"""

# ==============================================================================
# The limit of the administrative bypass
# ==============================================================================

BEYOND_ADMIN_ALL = frozenset({
    SystemPermissions.AUDIT_VIEW.value,
})
"""Permissions ``admin:all`` does not carry, and has to be granted for.

The audit journal records what was done to links and accounts, and an
administrator is the person who can do the most of it. A bypass that handed
them the record along with the powers would leave the journal proving
nothing about the one caller it is chiefly kept against -- which is what
NIST SP 800-53 AU-9 asks a system to prevent, and AC-5 the reason why.

**What this does not do.** It does not stop an administrator reading the
journal: they hold ``admin:manage_roles`` and can assign themselves
``auditor``, and they can read the file off the disk besides. Nothing
arranged inside one application can prevent that -- it takes a second
system that this one cannot write to, which is the first entry in
`docs/roadmap.md`. What the exception buys is that the short way round is
closed and the remaining way leaves a record: the grant is an event, and so
is the reading that follows it.

``logs:view`` is deliberately absent from this set. `application.log` and
`error.log` are operational journals -- an administrator reads them to do
the job, and withholding them would be ceremony rather than separation.
"""


class RBACAuthorizationService(AuthorizationService):
    """
    Determines if a caller has a given permission based on assigned roles.

    Users holding the ``admin:all`` permission are considered super-users
    and are granted implicit access to everything except what
    ``BEYOND_ADMIN_ALL`` names. That bypass is reachable only for an
    authenticated user -- an anonymous caller is answered from the ``guest``
    role and never reaches it.

    Attributes:
        uow_factory: Callable that returns a new Unit of Work instance.
        logger: Application logger.
    """

    def __init__(
        self,
        uow_factory: Callable[..., UnitOfWork],
        logger: Logger,
    ):
        """
        Args:
            uow_factory: Factory to create Unit of Work instances.
            logger: Application logger.
        """
        self.uow_factory = uow_factory
        self.logger = logger

    def is_allowed(
        self,
        user: Optional[User],
        permission: str,
    ) -> bool:
        """
        Check if a caller is allowed to perform an action.

        Args:
            user: The user entity (``None`` for anonymous).
            permission: Permission string (e.g., ``"link:create"``).

        Returns:
            ``True`` if the caller has the permission or is a super-admin.
        """
        if user is None:
            return self._anonymous_is_allowed(permission)
        # Admins bypass permission checks, with the exception named in
        # ``BEYOND_ADMIN_ALL``: the audit journal is not something the
        # administrative role carries by being administrative.
        if permission not in BEYOND_ADMIN_ALL and user.has_permission(
            SystemPermissions.ADMIN_ALL.value
        ):
            return True
        # Standard role-based check.
        return user.has_permission(permission)

    def _anonymous_is_allowed(self, permission: str) -> bool:
        """
        Check a permission for an unauthenticated caller.

        Opens a Unit of Work, so this branch must not be reached from
        inside an open one. Three use cases ask this service while doing
        their own database work, and each stays clear of it differently:
        ``DeleteLinkUseCase`` has already established that the caller is
        somebody, while ``ReadJournalUseCase`` and ``GetSecurityCountsUseCase``
        close the unit of work they loaded the actor with before they ask.
        Said as a list because it was said as "the only call site", and by
        then there were three.

        Args:
            permission: Permission string being checked.

        Returns:
            ``True`` if the ``guest`` role grants it and the ceiling allows it.
        """
        # Asked before the role is loaded, not after: outside the ceiling the
        # answer cannot change, so anonymous traffic pays no query for the
        # checks it is certain to fail -- which is nearly all of them.
        if permission not in ANONYMOUS_PERMISSION_CEILING:
            return False

        with self.uow_factory(read_only=True) as uow:
            guest_role = uow.roles.get_by_name(GUEST_ROLE_NAME)

        if guest_role is None:
            # Not "whatever a guest may have" -- this deployment has not said
            # what a guest may have. Falling back to the ceiling would turn a
            # maximum into a default, and a half-seeded database would be
            # indistinguishable from a configured one.
            self.logger.warning(
                "Guest role is missing; anonymous access denied",
                role=GUEST_ROLE_NAME,
                permission=permission,
            )
            return False

        granted = guest_role.has_permission(permission)
        if not granted:
            # Said out loud because the alternative is a silent 401 on a
            # public endpoint. A deployment seeded before this permission
            # existed looks exactly like a working one until someone reads
            # the role, and the operator has nothing to read otherwise.
            # Debug, not warning: refusing anonymous callers is a legitimate
            # configuration, and it would log on every request.
            self.logger.debug(
                "Guest role does not grant this permission",
                role=GUEST_ROLE_NAME,
                permission=permission,
            )
        return granted
