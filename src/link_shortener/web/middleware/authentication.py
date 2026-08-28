from typing import Optional
from flask import Flask, g, request

from link_shortener.application import (
    UnitOfWorkFactory, AuthenticationService, CurrentUserInfo,
    AuthorizationService, Logger
)


AUTH_SOURCE_HEADER = "header"
"""Marker for a request authenticated by the Authorization header."""

AUTH_SOURCE_COOKIE = "cookie"
"""Marker for a request authenticated by the access token cookie."""


class AuthenticationMiddleware:
    """
    Per-request authentication layer.

    Takes the token from the ``Authorization: Bearer <token>`` header, or,
    for browsers, from the ``access_token`` cookie -- server-rendered pages
    are reached by plain navigation, which cannot carry a header. Writes made
    on the cookie are covered by ``CsrfProtectionMiddleware``.

    Validates the token as an access token, loads the user from the database,
    and stores a lightweight user representation in ``g.current_user``.
    Additionally, loads the full domain User and stores it in g._domain_user,
    and exposes the authentication_service in g.authorization_service.

    The request stays anonymous when the token is not an access token, when
    the session it names has ended, or when the account is deactivated. The
    session check is what makes an access token revocable: on its own the
    token is a signed claim that nothing but its own expiry can stop.
    """

    def __init__(
            self,
            app: Flask,
            authentication_service: AuthenticationService,
            authorization_service: AuthorizationService,
            uow_factory: UnitOfWorkFactory,
            logger: Optional[Logger] = None
    ):
        """
        Args:
            app: The Flask application instance.
            authentication_service: Authentication service for token validation.
            uow_factory: Factory to create read-only Unit of Work
                instances for user lookups.
            logger: Application logger for diagnostics.
        """
        self.app = app
        self.authentication_service = authentication_service
        self.authorization_service = authorization_service
        self.uow_factory = uow_factory
        self.logger = logger
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
            g.auth_session_id = None
            g.authorization_service = self.authorization_service

            # CsrfProtectionMiddleware exempts header-authenticated requests,
            # so this must record the credential that actually carried the
            # request, not the one it appears to offer. It stays None until a
            # token has passed validation: a header holding an empty or
            # garbage token authenticates nothing and must not buy the
            # exemption on a request that otherwise rests on cookies.
            g.auth_token_source = None

            token = None
            token_source = None
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header[7:]
                token_source = AUTH_SOURCE_HEADER

            if not token:
                token = request.cookies.get("access_token")
                token_source = AUTH_SOURCE_COOKIE if token else None

            if not token:
                return

            # Only access tokens grant API access. A refresh token is a
            # long-lived credential meant solely for /auth/refresh; accepting
            # it here would make the short access-token lifetime meaningless.
            payload = self.authentication_service.validate_token(
                token, expected_type="access"
            )
            if not payload:
                return

            user_id = payload.get("sub")
            session_id = payload.get("sid")

            # An access token names the login it came from. Without that the
            # token would be unrevocable: logging out could only delete the
            # client's copy and leave any other copy working until it aged
            # out on its own.
            if not session_id:
                return

            if not user_id:
                return

            try:
                with self.uow_factory(read_only=True) as uow:
                    if not uow.refresh_sessions.chain_is_live(session_id):
                        return

                    user = uow.users.find_by_id(user_id)
                    # A deactivated account is treated as unauthenticated:
                    # blocking a user must revoke access immediately instead
                    # of waiting for the token to expire.
                    if user and user.is_active:
                        g.auth_session_id = session_id
                        # Set only once the request is genuinely acting as a
                        # user: the CSRF exemption keys off this, and a token
                        # that resolves to nobody must not earn it.
                        g.auth_token_source = token_source
                        g.current_user = CurrentUserInfo(
                            id=user.id,
                            email=user.email.value,
                            roles=[r.name for r in user.roles],
                            is_active=user.is_active,
                        )
                        # Also cache the full domain user for downstream use.
                        g._domain_user = user
            except Exception as e:
                # This hook runs before every view, so a database outage here
                # became a 500 on routes that need no database at all --
                # including /health, whose whole purpose is to report that
                # outage. The request continues as anonymous instead.
                if self.logger:
                    self.logger.error(
                        "Could not load the current user, continuing anonymously",
                        error=str(e),
                    )
                g.current_user = None
                g._domain_user = None
                g.auth_session_id = None
                g.auth_token_source = None
