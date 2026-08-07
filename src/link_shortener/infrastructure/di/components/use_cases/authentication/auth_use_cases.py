from dataclasses import dataclass
from typing import Callable

from link_shortener.application import (
    LoginUseCase,
    RegisterUseCase,
    AuthenticationService,
    Logger,
    UnitOfWork,
)


@dataclass
class AuthUseCasesComponent:
    """
    Provides factory methods for authentication-related use cases.

    Requires the Unit of Work factory, authentication service, logger,
    and the name of the default role assigned to new users.
    """

    uow_factory: Callable[[], UnitOfWork]
    authentication_service: AuthenticationService
    logger: Logger
    default_role_name: str

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

        Creates a new user with the default role.
        """
        return RegisterUseCase(
            uow_factory=self.uow_factory,
            authentication_service=self.authentication_service,
            logger=self.logger,
            default_role_name=self.default_role_name,
        )
