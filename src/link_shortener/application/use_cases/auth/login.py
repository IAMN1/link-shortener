from dataclasses import dataclass
from datetime import datetime, timezone

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.auth import LoginResponse
from link_shortener.application.dtos.user import UserResponse
from link_shortener.application.ports.auth.auth_service import AuthenticationService
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import DomainError


@dataclass
class LoginUseCase(BaseUseCase):
    """
    Authenticates a user by email and password.

    On success, generates an access token and a refresh token, and returns
    the user's profile. Raises a ``DomainError`` if the credentials are
    invalid, the account is inactive, or its address has not been
    confirmed. Only the last of the three says which it was.
    """
    authentication_service: AuthenticationService
    logger: Logger
    uow_factory: UnitOfWorkFactory

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

        if not user.email_verified:
            # Named, unlike the case above, and the difference is who the
            # answer is for. Deactivation is an administrator's decision
            # that the account holder has no part in and cannot undo, so
            # naming it only tells a guesser their guess landed. An
            # unconfirmed address is the holder's own unfinished business:
            # they are told what to do about it, and the only person who
            # gets that answer is one who already knows the password --
            # who has therefore learned nothing new about whether the
            # account exists.
            log.warning("Login attempt on unverified user", user_id=user.id)
            raise DomainError(
                "Confirm your email address before signing in",
                code="EMAIL_NOT_VERIFIED",
            )

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
