from typing import Optional
from flask import Flask, g, request

from link_shortener.application import (
    UnitOfWorkFactory, AuthenticationService, CurrentUserInfo,
    AuthorizationService, Logger
)
from link_shortener.domain.exceptions import DomainError
from link_shortener.domain.i18n import N_


AUTH_SOURCE_HEADER = "header"
"""Marker for a request authenticated by the Authorization header."""

AUTH_SOURCE_COOKIE = "cookie"
"""Marker for a request authenticated by the access token cookie."""

A_FAILED_HEADER_IS_IGNORED_ON = frozenset({
    "auth.refresh_token",
    "auth.logout",
    "health",
})
"""Endpoints where a presented token that fails is ignored, not refused.

Everywhere else a credential offered in an ``Authorization`` header and
found wanting is answered ``401``, for the reasons the class docstring
gives. These three are the exceptions, and each is one because the token
is not what the endpoint runs on.

``auth.refresh_token`` and ``auth.logout`` exist **for** the client whose
access token has expired: they identify the caller by the refresh token in
the cookie and never read this header. Refusing them on the strength of it
closes the only two doors out of that state -- measured on a live session
holding a valid refresh cookie and its own expired access token, with the
CSRF header correct::

    POST /auth/refresh   no header              -> 200, tokens issued
    POST /auth/refresh   + the expired token    -> 401 UNAUTHENTICATED
    POST /auth/logout    + the expired token    -> 401 UNAUTHENTICATED

and the same two calls answered ``200`` before the refusal existed. A
client that sends its ``Authorization`` on every request -- which is how
most of them are written -- could then neither refresh nor sign out.
RFC 6750 asks for ``invalid_token`` on a *protected resource*; these two
are not protected by this token.

``health`` is the observation route. It is already exempt from the rate
limiter for the same reason -- "``/health`` and everything under
``/static/`` are never throttled" -- and the class docstring below argues
that it must answer even when the database is unreachable. A monitor that
walks the service with one client, holding a token that has since expired,
was answered ``401`` where the whole point of the route is to say whether
the service is well.
"""


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

    A token that does not stand up leaves the request anonymous when it
    came from the cookie, and is refused with ``401`` when it came from an
    ``Authorization: Bearer`` header. The two are different acts. A stale
    cookie is what every browser sends after a session ends, and answering
    the landing page with ``401`` for it would lock a visitor out of a
    public page; a Bearer header is a caller deliberately presenting a
    credential, and RFC 6750 asks for ``invalid_token`` rather than
    silence -- "if the request included an expired access token, the
    resource server MUST include the ``invalid_token`` error code".

    Three endpoints are outside that rule and are named at the top of this
    module, with the measurement behind each: they do not run on this
    header, and two of them are how a client gets out of holding a token
    that has expired.

    Silence was measured costing more than a wrong status. A deactivated
    account's token answered ``401`` on ``/api/v1/links/mine`` and ``201``
    on ``POST /api/v1/shorten``, where the request was served as a guest:
    the caller was told their link was made, and it was made as somebody
    else's -- ``owner_id: null``, a guest lifetime, out of their own
    listing. A revoked credential went on being served.

    What leaves the request anonymous either way is the account being
    unreachable: a database outage is not a rejected credential, and this
    hook runs before every request including ``/health``, whose whole job
    is to report that outage.

    The token is checked as an access token, the session it names must
    still be live, and the account must still be active. The session check
    is what makes an access token revocable: on its own the token is a
    signed claim that nothing but its own expiry can stop.
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

            # A credential the caller chose to present, as opposed to one a
            # browser sends because it still has it. Every refusal below
            # goes through `_reject`, which answers 401 for the first and
            # falls back to anonymous for the second.
            #
            # Except on the three endpoints named at the top of this
            # module, where a presented token is treated like a stale
            # cookie: they do not run on it, and two of them are the way
            # out of holding one that has expired.
            presented = (
                token_source == AUTH_SOURCE_HEADER
                and request.endpoint not in A_FAILED_HEADER_IS_IGNORED_ON
                # And only where there is an endpoint at all. With no rule
                # matched -- an address this service does not serve, or a
                # method this address does not take -- the answer is about
                # the request line, not about the credential, and Werkzeug
                # has already worked it out: 404, or 405 with the `Allow`
                # header RFC 9110 requires. Refusing first replaced both
                # with 401 and told a caller nothing they could act on:
                # measured, `TRACE /api/v1/admin/users` carrying a token
                # this service does not accept answered 401, while the same
                # request with no token at all answered `405 Allow: GET,
                # HEAD, OPTIONS, POST`.
                #
                # Nothing is disclosed by that: which methods a path takes
                # is in the published document, and an unauthenticated
                # caller already gets the same answer.
                and request.url_rule is not None
            )

            def _reject(reason: str):
                """
                Refuse a presented credential; ignore a stale cookie.

                Args:
                    reason: What was wrong, for the log. Not sent to the
                        caller: which of the four checks a token failed
                        tells whoever holds it whether the account exists,
                        and the answer is the same either way.

                Raises:
                    DomainError: ``UNAUTHENTICATED``, when the credential
                        arrived in an ``Authorization`` header.
                """
                if not presented:
                    return None
                if self.logger:
                    self.logger.info(
                        "Bearer credential refused", reason=reason
                    )
                raise DomainError(
                    N_("Authentication required"), code="UNAUTHENTICATED"
                )

            # Only access tokens grant API access. A refresh token is a
            # long-lived credential meant solely for /auth/refresh; accepting
            # it here would make the short access-token lifetime meaningless.
            payload = self.authentication_service.validate_token(
                token, expected_type="access"
            )
            if not payload:
                return _reject("not a live access token")

            user_id = payload.get("sub")
            session_id = payload.get("sid")

            # An access token names the login it came from. Without that the
            # token would be unrevocable: logging out could only delete the
            # client's copy and leave any other copy working until it aged
            # out on its own.
            if not session_id:
                return _reject("names no login")

            if not user_id:
                return _reject("names no account")

            try:
                with self.uow_factory(read_only=True) as uow:
                    if not uow.refresh_sessions.chain_is_live(session_id):
                        return _reject("the login it came from has ended")

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
                    else:
                        # Missing or deactivated, and the two are one answer
                        # on purpose: telling them apart tells whoever holds
                        # the token whether the account exists.
                        return _reject("no live account behind it")
            except DomainError:
                # The refusal `_reject` raises, on its way out. Without this
                # the catch below swallowed it and the request continued
                # anonymously -- which is the exact behaviour being removed,
                # reinstated by the handler meant for a database outage.
                # Measured: the deactivated account's token went on
                # answering 201 on `POST /api/v1/shorten` with the refusal
                # written and the tests red.
                raise
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
