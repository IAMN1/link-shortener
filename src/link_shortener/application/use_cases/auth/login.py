from dataclasses import dataclass
from datetime import datetime, timezone

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.auth import LoginResponse
from link_shortener.application.dtos.user import UserResponse
from link_shortener.application.ports.auth.auth_service import AuthenticationService
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import DomainError
from link_shortener.domain.i18n import N_


@dataclass
class LoginUseCase(BaseUseCase):
    """
    Authenticates a user by email and password.

    On success, generates an access token and a refresh token, and returns
    the user's profile. Raises a ``DomainError`` if the credentials are
    invalid, the account is inactive, or its address has not been
    confirmed. Only the last of the three says which it was.

    All four outcomes reach the audit journal, and the refusals reach it
    named -- which is the opposite of what the caller is told. The response
    conflates a wrong password with a deactivated account so that a guesser
    learns nothing from the difference; the journal separates them so that
    an operator can. What makes the two safe to hold apart is that they are
    read through different doors: the response goes to whoever asked, the
    journal opens to ``audit:view``.

    Attributes:
        authentication_service: Checks the credentials and opens sessions.
        logger: Application logger.
        uow_factory: Callable that returns a new Unit of Work instance.
        audit_logger: Audit logger, where the outcome is recorded.
    """
    authentication_service: AuthenticationService
    logger: Logger
    uow_factory: UnitOfWorkFactory
    audit_logger: AuditLogger

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
        audit = self._get_audit_logger(self.audit_logger, context)
        log.info("Login attempt", email=email)

        user = self.authentication_service.authenticate(email, password)
        if not user:
            log.warning("Login failed", email=email)
            # No user id: nothing was authenticated, and the address is all
            # there is to say who the attempt was against. Whether it names
            # an account at all is a question this record deliberately does
            # not answer -- the same refusal covers both, here as in the
            # response.
            audit.log_login_failed(email=email, reason="invalid_credentials")
            raise DomainError(N_("Invalid email or password"), code="INVALID_CREDENTIALS")

        if not user.is_active:
            # Answered exactly like a wrong password. Saying "deactivated"
            # only when the password is right confirms both that the account
            # exists and that the password guess landed.
            log.warning("Login attempt on inactive user", user_id=user.id)
            # The journal is told which it was, and the account too: the
            # password was right, so this is a live credential being used
            # against an account somebody switched off -- the one refusal
            # here that says an intrusion may already have happened.
            audit.log_login_failed(
                email=email,
                reason="account_deactivated",
                target_user_id=user.id,
            )
            raise DomainError(N_("Invalid email or password"), code="INVALID_CREDENTIALS")

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
            audit.log_login_failed(
                email=email,
                reason="email_not_verified",
                target_user_id=user.id,
            )
            raise DomainError(
                N_("Confirm your email address before signing in"),
                code="EMAIL_NOT_VERIFIED",
            )

        # One column, by a conditional update, rather than saving the
        # entity back. The entity was read to check the password, which is
        # ~160 ms of bcrypt ago, and `save` writes every column it holds:
        # an account an administrator switched off during that window came
        # back active, and a password changed during it was replaced by
        # the old hash -- so the new password stopped working and the one
        # the change was made against went on working. The rule is
        # `JwtAuthenticationService.revoke_refresh_token`'s, applied here.
        user.last_login = datetime.now(timezone.utc)
        with self.uow_factory() as uow:
            uow.users.record_login(user.id, user.last_login)
            uow.commit()

        # Open a session and take its pair of tokens.
        tokens = self.authentication_service.create_session_tokens(user)

        log.info("login successful", user_id=user.id, email=user.email.value)

        # After the session exists, not before: a record written ahead of
        # `create_session_tokens` would claim a sign-in that a failure in
        # it never completed.
        audit.log_login_succeeded(
            target_user_id=user.id, email=user.email.value
        )

        user_dto = UserResponse.from_user(user)
        return LoginResponse(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            user=user_dto,
        )
