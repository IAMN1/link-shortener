from typing import Callable
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.infrastructure.auth.jwt_auth_service import JwtAuthenticationService
from link_shortener.infrastructure.auth.rbac_authorization_service import RBACAuthorizationService

class AuthComponent:
    """
    Provides singleton instances of the authentication and authorization
    services.

    The JWT service is initialised with the app secret, token lifetimes,
    and a factory for Unit of Work instances (used during authentication).
    """
    def __init__(self,
                 secret_key: str,
                 jwt_access_expire_minutes: int,
                 jwt_refresh_expire_days: int,
                 jwt_algorithm: str,
                 uow_factory: Callable[[], UnitOfWork],
    ):
        
        """
        Args:
            secret_key: Secret used to sign JWT tokens.
            jwt_access_expire_minutes: Access token lifetime in minutes.
            jwt_refresh_expire_days: Refresh token lifetime in days.
            jwt_algorithm: JWT signing algorithm (default HS256).
            uow_factory: Factory to create Unit of Work instances.
        """

        self.secret_key = secret_key
        self.access_expire = jwt_access_expire_minutes
        self.refresh_expire = jwt_refresh_expire_days
        self.algorithm = jwt_algorithm
        self.uow_factory = uow_factory

        self._authentication_service = None
        self._authorization_service = None

    def get_authentication_service(self) -> JwtAuthenticationService:
        """
        Return the singleton ``JwtAuthenticationService``.

        The service handles password hashing, user authentication, and
        token generation/validation.
        """
        if self._authentication_service is None:
            self._authentication_service = JwtAuthenticationService(
                uow_factory = self.uow_factory,
                secret_key=self.secret_key,
                access_expire_minutes=self.access_expire,
                refresh_expire_days=self.refresh_expire,
                algorithm=self.algorithm
            )
        return self._authentication_service

    def get_authorization_service(self) -> RBACAuthorizationService:
        """
        Return the singleton ``RBACAuthorizationService``.

        The service checks whether a user has a specific permission
        based on their assigned roles.
        """
        if self._authorization_service is None:
            self._authorization_service = RBACAuthorizationService()
        return self._authorization_service
