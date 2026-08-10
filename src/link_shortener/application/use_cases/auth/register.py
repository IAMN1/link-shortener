from dataclasses import dataclass
from typing import Callable

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.user import UserResponse
from link_shortener.application.ports.auth.auth_service import AuthenticationService
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.task_queue import TaskQueue
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import (
    DomainError, User, ValidationError,
    Email, PasswordHash
)
from link_shortener.domain.entities.email_verification import EmailVerification
from link_shortener.domain.value_objects.verification_token import (
    issue_token,
    token_digest,
)


@dataclass
class RegisterUseCase(BaseUseCase):
    """
    Creates a new user account with the default role.

    The password is hashed by the AuthenticationService before storage.

    The account starts unconfirmed and cannot sign in until the address is
    proven readable. The confirmation is issued in the same transaction as
    the account, so there is no state where one exists without the other,
    and handed to the queue afterwards -- a message cannot be sent for a
    row that has not been committed yet.

    A message that fails to go out does not undo the registration. The
    account and its token are already stored, so the person can ask for
    another one; rolling back instead would make the mail server able to
    stop registration outright, and would tell an anonymous caller that it
    is down.
    """
    uow_factory: Callable[[], UnitOfWork]
    authentication_service: AuthenticationService
    logger: Logger
    default_role_name: str  # Role assigned to new users by default.
    task_queue: TaskQueue
    verification_ttl_hours: int

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
            hashed = self.authentication_service.hash_password(password)
            password_hash_vo = PasswordHash(hashed)

            # Retrieve default role
            default_role = uow.roles.get_by_name(self.default_role_name)
            if not default_role:
                log.error("Default role not found", role_name=self.default_role_name)
                # A server failure in substance: the caller did nothing
                # wrong and retrying with different input will not help.
                # The message says so and no longer names the missing
                # role, which told an anonymous caller which part of the
                # deployment is misconfigured.
                #
                # The status is still 400, because the controller answers
                # every DomainError that way -- so the code, not the
                # status, is what distinguishes this from a bad request.
                raise DomainError(
                    "Registration is unavailable",
                    code="CONFIGURATION_ERROR",
                )

            # Create user entity
            user = User.create(
                email=email_vo,
                password_hash=password_hash_vo,
                roles=[default_role]
            )

            saved_user = uow.users.save(user)

            token = issue_token()
            uow.email_verifications.save(
                EmailVerification.issue(
                    user_id=saved_user.id,
                    token_hash=token_digest(token),
                    ttl_hours=self.verification_ttl_hours,
                )
            )
            uow.commit()

        log.info("User registered", user_id=saved_user.id, email=email)

        if not self.task_queue.enqueue_verification_email(email, token, context):
            # Said out loud rather than swallowed: the account exists and
            # cannot be used, and nobody will find out from the response,
            # which is the same either way.
            log.error(
                "Registered account has no confirmation message",
                user_id=saved_user.id,
                email=email,
            )

        return UserResponse.from_user(saved_user)
