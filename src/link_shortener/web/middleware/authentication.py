from typing import Callable
from flask import Flask, g, request

from link_shortener.application import AuthenticationService, UnitOfWork, CurrentUserInfo


class AuthenticationMiddleware:
    """
    Per-request authentication layer.

    Reads the ``Authorization: Bearer <token>`` header, validates it,
    loads the user from the database, and stores a lightweight user
    representation in ``g.current_user``.
    """

    def __init__(
            self,
            app: Flask,
            auth_service: AuthenticationService,
            uow_factory: Callable[[], UnitOfWork]
    ):
        """
        Args:
            app: The Flask application instance.
            auth_service: Authentication service for token validation.
            uow_factory: Factory to create read-only Unit of Work
                instances for user lookups.
        """
        self.app = app
        self.auth_service = auth_service
        self.uow_factory = uow_factory
        self._register_handler()
    
    def _register_handler(self):
        """Register the ``before_request`` hook that extracts the user."""

        @self.app.before_request
        def load_current_user():
            g.current_user = None
            auth_header = request.headers.get("Authorization")

            if not auth_header or not auth_header.startswith("Bearer "):
                return
            
            token = auth_header[7:]
            payload = self.auth_service.validate_token(token)
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
