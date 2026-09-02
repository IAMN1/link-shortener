from dataclasses import dataclass

from link_shortener.application import (
    UnitOfWorkFactory, AuditLogger, ChangePasswordUseCase,
    CleanUnverifiedAccountsUseCase,
    LoginUseCase, RefreshSessionUseCase, RegisterUseCase,
    RequestPasswordResetUseCase,
    ResendVerificationUseCase, ResetPasswordUseCase,
    SendAccountExistsEmailUseCase, SendPasswordResetEmailUseCase,
    SendVerificationEmailUseCase, SignOutUseCase,
    VerifyEmailUseCase, AuthenticationService, Logger, Mailer,
    MailTemplates, RateLimiter, TaskQueue, UserManagementService
)


@dataclass
class AuthUseCasesComponent:
    """
    Provides factory methods for authentication-related use cases.

    Requires the Unit of Work factory, authentication service, logger,
    audit logger, the name of the default role assigned to new users, the
    user service that hashes a password on its way into an account, and
    everything the mailed links need: a queue to hand the message to, a
    mailer and templates for the worker that sends it, and the three
    lifetimes -- the confirmation's, the reset token's, and the window an
    account may stay unconfirmed in.
    """

    uow_factory: UnitOfWorkFactory
    authentication_service: AuthenticationService
    user_service: UserManagementService
    logger: Logger
    audit_logger: AuditLogger
    default_role_name: str
    task_queue: TaskQueue
    mailer: Mailer
    templates: MailTemplates
    base_url: str
    verification_ttl_hours: int
    password_reset_ttl_minutes: int
    unverified_ttl_hours: int
    rate_limiter: RateLimiter
    login_account_failure_limit: int
    login_account_failure_period: int

    def get_login_use_case(self) -> LoginUseCase:
        """
        Return a configured ``LoginUseCase``.

        The use case authenticates a user by email/password and returns
        JWT tokens.
        """
        return LoginUseCase(
            authentication_service=self.authentication_service,
            logger=self.logger,
            uow_factory=self.uow_factory,
            audit_logger=self.audit_logger,
            rate_limiter=self.rate_limiter,
            account_failure_limit=self.login_account_failure_limit,
            account_failure_period=self.login_account_failure_period,
        )

    def get_change_password_use_case(self) -> ChangePasswordUseCase:
        """
        Return a configured ``ChangePasswordUseCase``.

        Replaces the password of the account that is asking, revokes every
        session it had, and opens a new one for the caller.
        """
        return ChangePasswordUseCase(
            uow_factory=self.uow_factory,
            authentication_service=self.authentication_service,
            user_service=self.user_service,
            logger=self.logger,
            audit_logger=self.audit_logger,
        )

    def get_sign_out_use_case(self) -> SignOutUseCase:
        """Return a configured ``SignOutUseCase``.

        Returns:
            The use case that retires one session and records it.
        """
        return SignOutUseCase(
            authentication_service=self.authentication_service,
            uow_factory=self.uow_factory,
            audit_logger=self.audit_logger,
            logger=self.logger,
        )

    def get_refresh_session_use_case(self) -> RefreshSessionUseCase:
        """Return a configured ``RefreshSessionUseCase``.

        Returns:
            The use case that rotates a refresh token and records a replay.
        """
        return RefreshSessionUseCase(
            authentication_service=self.authentication_service,
            audit_logger=self.audit_logger,
            logger=self.logger,
        )

    def get_register_use_case(self) -> RegisterUseCase:
        """
        Return a configured ``RegisterUseCase``.

        Creates a new user with the default role, issues a confirmation
        token, and hands the message to the queue.
        """
        return RegisterUseCase(
            uow_factory=self.uow_factory,
            authentication_service=self.authentication_service,
            logger=self.logger,
            audit_logger=self.audit_logger,
            default_role_name=self.default_role_name,
            task_queue=self.task_queue,
            verification_ttl_hours=self.verification_ttl_hours,
        )

    def get_verify_email_use_case(self) -> VerifyEmailUseCase:
        """
        Return a configured ``VerifyEmailUseCase``.

        Spends a confirmation token and marks the address as proven.
        """
        return VerifyEmailUseCase(
            uow_factory=self.uow_factory,
            logger=self.logger,
            audit_logger=self.audit_logger,
        )

    def get_resend_verification_use_case(self) -> ResendVerificationUseCase:
        """
        Return a configured ``ResendVerificationUseCase``.

        Issues a fresh confirmation and retires the outstanding ones.
        """
        return ResendVerificationUseCase(
            uow_factory=self.uow_factory,
            task_queue=self.task_queue,
            logger=self.logger,
            ttl_hours=self.verification_ttl_hours,
        )

    def get_request_password_reset_use_case(self) -> RequestPasswordResetUseCase:
        """
        Return a configured ``RequestPasswordResetUseCase``.

        Issues a reset token for an address and hands the message to the
        queue, retiring any token the account still had outstanding.
        """
        return RequestPasswordResetUseCase(
            uow_factory=self.uow_factory,
            task_queue=self.task_queue,
            logger=self.logger,
            ttl_minutes=self.password_reset_ttl_minutes,
        )

    def get_reset_password_use_case(self) -> ResetPasswordUseCase:
        """
        Return a configured ``ResetPasswordUseCase``.

        Spends a reset token, writes the new password, and revokes every
        session the account held.
        """
        return ResetPasswordUseCase(
            uow_factory=self.uow_factory,
            user_service=self.user_service,
            logger=self.logger,
            audit_logger=self.audit_logger,
        )

    def get_send_password_reset_email_use_case(self) -> SendPasswordResetEmailUseCase:
        """
        Return a configured ``SendPasswordResetEmailUseCase``.

        Builds and sends one message. Used by the Celery task and by the
        synchronous fallback, so both send the same thing.
        """
        return SendPasswordResetEmailUseCase(
            mailer=self.mailer,
            templates=self.templates,
            logger=self.logger,
            base_url=self.base_url,
            ttl_minutes=self.password_reset_ttl_minutes,
        )

    def get_send_verification_email_use_case(self) -> SendVerificationEmailUseCase:
        """
        Return a configured ``SendVerificationEmailUseCase``.

        Builds and sends one message. Used by the Celery task and by the
        synchronous fallback, so both send the same thing.
        """
        return SendVerificationEmailUseCase(
            mailer=self.mailer,
            templates=self.templates,
            logger=self.logger,
            base_url=self.base_url,
            ttl_hours=self.verification_ttl_hours,
        )

    def get_send_account_exists_email_use_case(self) -> SendAccountExistsEmailUseCase:
        """
        Return a configured ``SendAccountExistsEmailUseCase``.

        Builds and sends the notice that an address is already taken.
        Used by the Celery task and by the synchronous fallback, so both
        send the same thing.
        """
        return SendAccountExistsEmailUseCase(
            mailer=self.mailer,
            templates=self.templates,
            logger=self.logger,
            base_url=self.base_url,
        )

    def get_clean_unverified_accounts_use_case(self) -> CleanUnverifiedAccountsUseCase:
        """
        Return a configured ``CleanUnverifiedAccountsUseCase``.

        Deletes registrations nobody confirmed, and dead tokens with them.
        """
        return CleanUnverifiedAccountsUseCase(
            uow_factory=self.uow_factory,
            logger=self.logger,
            audit_logger=self.audit_logger,
            unverified_ttl_hours=self.unverified_ttl_hours,
        )
