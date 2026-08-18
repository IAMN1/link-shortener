from dataclasses import dataclass
from typing import List, Optional

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.user import UserResponse
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.services.user_management_service import UserManagementService
from link_shortener.application.use_cases.admin.privilege_guard import (
    require_may_grant_roles,
)
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import DomainError
from link_shortener.domain.i18n import N_


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
            DomainError: If the admin is not authorized or a business rule is violated.
        """
        log = self._get_logger(self.logger, context)
        audit = self._get_audit_logger(self.audit_logger, context)

        with self.uow_factory() as uow:
            roles = None
            if role_names:
                roles = []
                for name in role_names:
                    role = uow.roles.get_by_name(name)
                    if not role:
                        raise DomainError(
                                  f"Role '{name}' not found",
                                  code="VALIDATION_ERROR",
                                  template=N_("Role '%(name)s' not found"),
                                  params={"name": name},
                              )
                    roles.append(role)

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
