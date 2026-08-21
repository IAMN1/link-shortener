from dataclasses import dataclass

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.services.role_management_service import RoleManagementService
from link_shortener.application.use_cases.admin.privilege_guard import (
    require_administrator_survives_without,
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
        logger: Application logger.
        audit_logger: Audit logger, where the removal is recorded -- it
            takes the role's permissions off everyone who wore it.
    """
    uow_factory: UnitOfWorkFactory
    role_service: RoleManagementService
    logger: Logger
    audit_logger: AuditLogger

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

            # The two refusals -- no such role, and a role the service owns
            # -- are raised by the service as domain errors of their own.
            # They used to arrive as ``LookupError`` and ``ValueError`` and
            # be translated here into codes; the vocabulary is now one, and
            # the status table keeps deciding: 404 for the first, like the
            # neighbouring `delete_user`, and 400 for the second.
            self.role_service.delete_role(uow, role_name)
            uow.commit()

            log.info("Role deleted", role_name=role_name)
            audit.log_role_deleted(role=role_name)
