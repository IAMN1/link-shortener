from typing import Callable
from flask import Flask, g, request

from link_shortener.application import (
    AuthenticationService, UnitOfWork, 
    CurrentUserInfo, AuthorizationService
)


class AuthenticationMiddleware:
    """
    Per-request authentication layer.

    Reads the ``Authorization: Bearer <token>`` header, validates it,
    loads the user from the database, and stores a lightweight user
    representation in ``g.current_user``.
    Additionally, loads the full domain User and stores it in g._domain_user,
    and exposes the authentication_service in g.authorization_service.
    """

    def __init__(
            self,
            app: Flask,
            authentication_service: AuthenticationService,
            authorization_service: AuthorizationService,
            uow_factory: Callable[[], UnitOfWork]
    ):
        """
        Args:
            app: The Flask application instance.
            authentication_service: Authentication service for token validation.
            uow_factory: Factory to create read-only Unit of Work
                instances for user lookups.
        """
        self.app = app
        self.authentication_service = authentication_service
        self.authorization_service = authorization_service
        self.uow_factory = uow_factory
        self._register_handler()
    
    def _register_handler(self):
        """Register the ``before_request`` hook that extracts the user."""

        @self.app.before_request
        def load_current_user():
            # Skip static file requests to avoid unnecessary DB queries.
            if request.path.startswith('/static/'):
                return

            g.current_user = None
            g._domain_user = None
            g.authorization_service = self.authorization_service

            token = None
            # 1. Try the Authorization header first.
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header[7:]

            # 2. Fall back to the access_token cookie.
            if not token:
                token = request.cookies.get("access_token")

            if not token:
                return

            payload = self.authentication_service.validate_token(token)
            if not payload:
                return
            
            user_id = payload.get("sub")
            if user_id:
                with self.uow_factory(read_only=True) as uow:
                    user = uow.users.find_by_id(user_id)
                    if user:
                        g.current_user = CurrentUserInfo(
                            id=user.id,
                            email=user.email.value,
                            roles=[r.name for r in user.roles],
                            is_active=user.is_active,
                        )
                        # Also cache the full domain user for downstream use.
                        g._domain_user = user
