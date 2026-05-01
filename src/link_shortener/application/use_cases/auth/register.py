from dataclasses import dataclass
from typing import Callable

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.user import UserResponse
from link_shortener.application.ports.auth.auth_service import AuthenticationService
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import (
    User, ValidationError,
    Email, PasswordHash
)


@dataclass
class RegisterUseCase(BaseUseCase):
    """
    Creates a new user account with the default role.

    The password is hashed by the AuthenticationService before storage.
    """
    uow_factory: Callable[[], UnitOfWork]
    auth_service: AuthenticationService
    logger: Logger
    default_role_name: str  # роль, назначаемая пользователю по умолчанию

    def execute(self, email: str, password: str, context: RequestContext) -> UserResponse:
        """
        Register a new user.

        Args:
            email: Desired email.
            password: Plain-text password.
            context: Request context.

        Returns:
            UserResponse for the newly created user.

        Raises:
            ValidationError: If the email is invalid or already registered.
        """
        log = self._get_logger(self.logger, context)
        log.info("Registration attempt", email=email)

        # Validate email using domain value object
        email_vo = Email(email)

        with self.uow_factory() as uow:

            # Check for existing user
            if uow.users.find_by_email(email_vo):
                raise ValidationError("Email already registered", field="email")
        
            # Hash the password
            hashed = self.auth_service.hash_password(password)
            password_hash_vo = PasswordHash(hashed)

            # Retrieve default role
            default_role = uow.roles.get_by_name(self.default_role_name)
            if not default_role:
                log.error("Default role not found", role_name=self.default_role_name)
                raise ValidationError(
                    "System configuration error: default role missing",
                    field="system"
                )

            # Create user entity
            user = User.create(
                email=email_vo,
                password_hash=password_hash_vo,
                roles=[default_role]
            )

            saved_user = uow.users.save(user)
            uow.commit()

        log.info("User registered", user_id=saved_user.id, email=email)
        return UserResponse.from_user(saved_user)
