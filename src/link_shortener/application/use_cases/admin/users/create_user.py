from dataclasses import dataclass
from typing import List, Optional

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.user import UserResponse
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.services.role_management_service import RoleManagementService
from link_shortener.application.services.user_management_service import UserManagementService
from link_shortener.application.use_cases.admin.privilege_guard import (
    require_may_grant_roles,
)
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain.policies.role_policy import (
    require_roles_are_assignable,
)


@dataclass
class CreateUserUseCase(BaseUseCase):
    """
    Creates a new user account with optional custom roles.

    Requires the ``admin:manage_users`` permission.

    Attributes:
        uow_factory: Callable factory for creating Unit of Work instances.
        user_service: Service that creates the account itself.
        logger: Application logger.
        audit_logger: Audit logger, where the new account is recorded along
            with what it was given.
    """

    uow_factory: UnitOfWorkFactory
    user_service: UserManagementService
    logger: Logger
    audit_logger: AuditLogger

    def execute(
            self,
            email: str,
            password: str,
            context: RequestContext,
            role_names: Optional[List[str]] = None,
            is_active: bool = True,
    ) -> UserResponse:
        """
        Create a new user.

        Args:
            email: Email address.
            password: Plain-text password.
            context: Request context with admin info.
            roles: Specific roles to assign; if None, the default role is used.
            is_active: Whether the account is active at creation.

        Returns:
            UserResponse for the newly created user.

        Raises:
            RoleNotAssignableError: If a named role is one no account may
                wear, answered 400.
            RoleNotFoundError: If a named role does not exist, answered
                404 -- the answer the role endpoints give that question.
            DomainError: If the admin is not authorized or a business rule is violated.
        """
        log = self._get_logger(self.logger, context)
        audit = self._get_audit_logger(self.audit_logger, context)

        with self.uow_factory() as uow:
            roles = None
            if role_names:
                # The same door ``UpdateUserRolesUseCase`` opens, for the
                # reason written there: a name nothing carries answered
                # 400 here and 404 on the role endpoints.
                roles = RoleManagementService.resolve_roles(uow, role_names)

                # What is wrong with the request, before who is asking --
                # the ordering `UpdateUserRolesUseCase` uses, and for the
                # same reason. ``User.create`` asks this too and is the
                # door every path goes through, but it asks last, so
                # ``{"roles": ["guest"]}`` answered three ways for one
                # unanswerable request: ``ROLE_NOT_ASSIGNABLE`` to an
                # administrator, and to a caller holding only
                # ``admin:manage_users`` -- measured -- "You cannot grant
                # permissions you do not hold yourself: link:create,
                # stats:view_basic". That reads as "obtain those two and
                # retry", and no account may wear ``guest`` either way.
                require_roles_are_assignable(roles)

                # Creating an account is another way of handing out a role,
                # so it answers to the same rule as reassigning one.
                require_may_grant_roles(context, uow, roles)

            try:
                new_user = self.user_service.create_user(
                    uow=uow,
                    email=email,
                    password=password,
                    roles=roles,
                    is_active=is_active,
                )
                uow.commit()

                log.info("User created by admin", new_user_id=new_user.id)
                # The roles are read off the account rather than off
                # ``role_names``: asked for none, it is given the default
                # one, and a record repeating the empty request would say
                # an account was created with no entitlements at all.
                audit.log_user_created(
                    target_user_id=new_user.id,
                    email=email,
                    roles=[role.name for role in new_user.roles],
                )
                return UserResponse.from_user(new_user)
            except Exception as e:
                log.error("User creation failed", error=str(e))
                raise
