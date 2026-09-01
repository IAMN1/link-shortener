from dataclasses import dataclass

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.domain.exceptions import DomainError
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.services.role_management_service import RoleManagementService
from link_shortener.application.use_cases.admin.privilege_guard import (
    require_administrator_survives_without,
)
from link_shortener.application.services.user_management_service import (
    UserManagementService,
)
from link_shortener.application.use_cases.base_use_case import BaseUseCase


@dataclass
class DeleteRoleUseCase(BaseUseCase):
    """
    Deletes a role that is not marked as a system role.

    Requires the caller to have the ``admin:manage_roles`` permission.

    Attributes:
        uow_factory: Callable factory for creating Unit of Work instances.
        role_service: Service that removes the role itself.
        user_service: Service the fallback role is assigned through, so
            that both doors a role reaches an account by ask the same
            policy.
        logger: Application logger.
        audit_logger: Audit logger, where the removal is recorded -- it
            takes the role's permissions off everyone who wore it.
        default_role_name: The role an account falls back to when this
            deletion leaves it with none. The same name registration
            grants, read from one setting rather than written twice.
    """
    uow_factory: UnitOfWorkFactory
    role_service: RoleManagementService
    user_service: UserManagementService
    logger: Logger
    audit_logger: AuditLogger
    default_role_name: str

    def execute(
            self,
            role_name: str,
            context: RequestContext
    ) -> None:
        """
        Delete a role by name.

        Args:
            role_name: Unique name of the role to delete.
            context: Request context containing current user info.

        Returns:
            Nothing. It used to return ``True``, unconditionally: every
            other outcome leaves by an exception, so the value carried no
            information and the route that read it had a branch that
            could not run.

        Raises:
            RoleNotFoundError: When there is no such role, which the status
                table answers 404.
            DomainError: With code ``FORBIDDEN`` when deleting the role
                would leave the system without an administrator.
            RoleIsSystemError: When the role exists but is a system role,
                answered 400 -- the request named something real and asked
                for something the service does not do.
        """

        log = self._get_logger(self.logger, context)
        audit = self._get_audit_logger(self.audit_logger, context)

        with self.uow_factory() as uow:
            # Asked before the deletion, in the transaction that performs
            # it: a role carrying ``admin:all`` may be the only thing
            # making anybody an administrator, and taking it away is the
            # same loss as re-roling the last one. Read here rather than
            # taken from the service, which raises rather than returns
            # when the name is not there.
            doomed = uow.roles.get_by_name(role_name)
            # Only for a role that can actually go. A system role is
            # refused whatever the count says, and asking first made one
            # request answer two ways: ``DELETE /admin/roles/admin`` came
            # back ``ROLE_IS_SYSTEM`` while two administrators existed and
            # "this would leave the system without an administrator" while
            # one did -- for a role that is never deletable either way.
            if doomed is not None and not doomed.is_system:
                require_administrator_survives_without(uow, doomed)

            # Counted before the deletion, because afterwards there is
            # nothing left wearing the role to count. It is the only
            # measure of what this reached: the role comes off every
            # account at once, and none of them is touched individually.
            holders = uow.users.count_with_role(doomed.id) if doomed else 0

            # The two refusals -- no such role, and a role the service owns
            # -- are raised by the service as domain errors of their own.
            # They used to arrive as ``LookupError`` and ``ValueError`` and
            # be translated here into codes; the vocabulary is now one, and
            # the status table keeps deciding: 404 for the first, like the
            # neighbouring `delete_user`, and 400 for the second.
            # Who wore it, not just how many: the accounts this leaves
            # bare have to be put back on the default role, and that
            # needs their identity. Read before the deletion, because
            # afterwards nothing wears the role.
            wearers = uow.users.ids_with_role(doomed.id) if doomed else []

            self.role_service.delete_role(uow, role_name)

            rerolled = self._put_the_bare_ones_back(
                uow, wearers, log, audit, role_name
            )
            uow.commit()

        log.info(
            "Role deleted",
            role_name=role_name,
            holders=holders,
            rerolled=rerolled,
        )
        audit.log_role_deleted(role=role_name, holders=holders)

    def _put_the_bare_ones_back(
        self, uow, wearers, log, audit, role_name: str
    ) -> int:
        """
        Give the default role to accounts this deletion left with none.

        Deleting a role takes it off every account at once. An account
        whose only role it was is then left with an empty set, and an
        empty set is not the same as the least privilege -- measured: such
        an account signed in (200) and was then refused everything,
        including `POST /api/v1/shorten`, which an anonymous caller may
        do. It could not be told apart from a working account until it
        tried something, and nothing said so at deletion time.

        The default role rather than the one that was deleted: what the
        administrator asked for was that the role stop existing, and
        recreating it under another name would be answering a different
        request. This is the same role registration grants, and it goes
        through the same guard, so a deployment that has pointed
        ``DEFAULT_ROLE_NAME`` at something unassignable is refused here as
        it is there.

        Args:
            uow: The unit of work the deletion runs in.
            wearers: Ids of the accounts that wore the deleted role.
            log: Logger already bound to this request.

        Returns:
            How many accounts were put back on the default role.
        """
        if not wearers:
            return 0

        fallback = uow.roles.get_by_name(self.default_role_name)
        if fallback is None:
            # Said rather than raised: the role is already gone and the
            # transaction is worth keeping. What is lost is the fallback,
            # and an operator reading this knows which accounts to look at.
            log.warning(
                "Accounts left without a role and the default role is missing",
                default_role_name=self.default_role_name,
                accounts=len(wearers),
            )
            return 0

        rerolled = 0
        for user_id in wearers:
            account = uow.users.find_by_id(user_id)
            if account is None or account.roles:
                continue
            # Through the service rather than by writing the entity here:
            # it is one of the two doors a role reaches an account by, and
            # the assignability policy is asked at both. A deployment that
            # has pointed `DEFAULT_ROLE_NAME` at something unassignable is
            # refused here exactly as registration refuses it.
            #
            # Caught rather than let out, for the reason the branch above
            # gives about the missing fallback: the role is already gone
            # and the transaction is worth keeping. Let out, this refusal
            # rolled back the deletion itself -- so a deployment with an
            # unassignable default answered "cannot delete this role" and
            # named the wrong reason.
            try:
                self.user_service.update_roles(uow, user_id, [fallback])
            except DomainError as refusal:
                log.warning(
                    "An account could not be put back on the default role",
                    default_role_name=self.default_role_name,
                    user_id=user_id,
                    reason=str(refusal),
                )
                continue

            # On the record, because it is a change to what that account
            # may do -- the rule this vocabulary is built on. It arrives
            # through a deletion rather than through the roles endpoint,
            # and an investigator asking "why does this account hold the
            # default role" has nothing else to read.
            audit.log_roles_changed(
                target_user_id=user_id,
                roles_before=[role_name],
                roles_after=[fallback.name],
            )
            rerolled += 1

        if rerolled:
            log.info(
                "Accounts put back on the default role",
                default_role_name=self.default_role_name,
                accounts=rerolled,
            )
        return rerolled
