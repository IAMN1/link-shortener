from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.auth import LoginResponse
from link_shortener.application.dtos.user import UserResponse
from link_shortener.application.ports.auth.auth_service import AuthenticationService
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import DomainError


@dataclass
class LoginUseCase(BaseUseCase):
    """
    Authenticates a user by email and password.

    On success, generates an access token and a refresh token, and returns
    the user's profile. Raises a ``DomainError`` if credentials are invalid
    or the account is inactive.
    """
    authentication_service: AuthenticationService
    logger: Logger
    uow_factory: Callable[[], UnitOfWork]

    def execute(
        self, email: str, password: str, context: RequestContext
    ) -> LoginResponse:
        """
        Perform login.

        Args:
            email: Registered email.
            password: Plain-text password.
            context: Request context containing client metadata.

        Returns:
            LoginResponse with tokens and user data.

        Raises:
            DomainError: If authentication fails. A deactivated account is
                reported as invalid credentials so that the response does
                not distinguish the two cases.
        """
        log = self._get_logger(self.logger, context)
        log.info("Login attempt", email=email)

        user = self.authentication_service.authenticate(email, password)
        if not user:
            log.warning("Login failed", email=email)
            raise DomainError("Invalid email or password", code="INVALID_CREDENTIALS")

        if not user.is_active:
            # Answered exactly like a wrong password. Saying "deactivated"
            # only when the password is right confirms both that the account
            # exists and that the password guess landed.
            log.warning("Login attempt on inactive user", user_id=user.id)
            raise DomainError("Invalid email or password", code="INVALID_CREDENTIALS")

        # Update last_login timestamp.
        user.last_login = datetime.now(timezone.utc)
        with self.uow_factory() as uow:
            uow.users.save(user)
            uow.commit()

        # Open a session and take its pair of tokens.
        tokens = self.authentication_service.create_session_tokens(user)

        log.info("login successful", user_id=user.id, email=user.email.value)

        user_dto = UserResponse.from_user(user)
        return LoginResponse(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            user=user_dto,
        )
