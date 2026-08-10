from dataclasses import dataclass
from typing import Callable

from link_shortener.application import (
    CleanUnverifiedAccountsUseCase,
    LoginUseCase,
    RegisterUseCase,
    ResendVerificationUseCase,
    SendVerificationEmailUseCase,
    VerifyEmailUseCase,
    AuthenticationService,
    Logger,
    Mailer,
    MailTemplates,
    TaskQueue,
    UnitOfWork,
)


@dataclass
class AuthUseCasesComponent:
    """
    Provides factory methods for authentication-related use cases.

    Requires the Unit of Work factory, authentication service, logger,
    the name of the default role assigned to new users, and everything the
    address confirmation needs: a queue to hand the message to, a mailer
    and templates for the worker that sends it, and the two lifetimes.
    """

    uow_factory: Callable[[], UnitOfWork]
    authentication_service: AuthenticationService
    logger: Logger
    default_role_name: str
    task_queue: TaskQueue
    mailer: Mailer
    templates: MailTemplates
    base_url: str
    verification_ttl_hours: int
    unverified_ttl_hours: int

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

    def get_clean_unverified_accounts_use_case(self) -> CleanUnverifiedAccountsUseCase:
        """
        Return a configured ``CleanUnverifiedAccountsUseCase``.

        Deletes registrations nobody confirmed, and dead tokens with them.
        """
        return CleanUnverifiedAccountsUseCase(
            uow_factory=self.uow_factory,
            logger=self.logger,
            unverified_ttl_hours=self.unverified_ttl_hours,
        )
