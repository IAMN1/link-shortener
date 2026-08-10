"""
Authentication controller -- /api/v1/auth/* endpoints.

Handles login, registration, token refresh, and logout.
"""

from flask import Blueprint, current_app, g, jsonify, make_response, request

from link_shortener.application import (
    AuthenticationService,
    LoginUseCase,
    RegisterUseCase,
    ResendVerificationUseCase,
    VerifyEmailUseCase,
)
from link_shortener.domain import DomainError, ValidationError
from link_shortener.web.middleware.csrf import (
    CSRF_COOKIE_NAME, build_csrf_token, set_csrf_cookie
)
from link_shortener.web.responses import error_response
from link_shortener.web.security.context import create_request_context


def _decoded_body():
    """
    Decode the request body, treating anything undecodable as absent.

    ``get_json(silent=True)`` swallows a malformed body but not a body the
    decoder cannot get through at all: ``"[" * 10000`` is twenty kilobytes
    and exhausts the stack, and ``RecursionError`` is not a ``ValueError``,
    so it escaped the silent parse and left every endpoint here answering
    500 to an unauthenticated request.

    Returns:
        The decoded body, or ``None``.
    """
    try:
        return request.get_json(silent=True)
    except RecursionError:
        return None


def _read_credentials():
    """
    Pull ``email`` and ``password`` out of the request body.

    Guards the shape of the body as well as its contents: a JSON document
    that is not an object, or fields that are not strings, would otherwise
    crash further down and surface as a 500.

    Returns:
        Tuple of (email, password), or (None, None) if the body does not
        carry usable credentials.
    """
    data = _decoded_body()
    if not isinstance(data, dict):
        return None, None

    email = data.get("email")
    password = data.get("password")
    if not isinstance(email, str) or not isinstance(password, str):
        return None, None

    return email or None, password or None


def _read_refresh_token() -> str:
    """
    Take the refresh token from wherever this client keeps it.

    Browsers send the HttpOnly cookie; programmatic clients have no cookie
    jar and pass the token they were given at login in the body.

    Returns:
        The refresh token, or None if the request carries none.
    """
    cookie_token = request.cookies.get("refresh_token")
    if cookie_token:
        return cookie_token

    body = _decoded_body()
    if isinstance(body, dict):
        token = body.get("refresh_token")
        if isinstance(token, str) and token:
            return token

    return None


def _access_cookie_max_age() -> int:
    """
    Lifetime of the access token cookie, in seconds.

    Derived from the configured token lifetime so the cookie and the JWT
    inside it always expire together.

    Returns:
        Cookie ``max_age`` in seconds.
    """
    return current_app.config.get("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", 15) * 60


def _refresh_cookie_max_age() -> int:
    """
    Lifetime of the refresh token cookie, in seconds.

    Returns:
        Cookie ``max_age`` in seconds.
    """
    return current_app.config.get("JWT_REFRESH_TOKEN_EXPIRE_DAYS", 7) * 24 * 3600


class AuthController:
    """
    Controller for authentication endpoints (login, token refresh, logout, register).
    """

    def __init__(
        self, 
        authentication_service: AuthenticationService,
        login_use_case: LoginUseCase,
        register_use_case: RegisterUseCase,
        verify_email_use_case: VerifyEmailUseCase,
        resend_verification_use_case: ResendVerificationUseCase,
    ):
        self.authentication_service = authentication_service
        self.login_use_case = login_use_case
        self.register_use_case = register_use_case
        self.verify_email_use_case = verify_email_use_case
        self.resend_verification_use_case = resend_verification_use_case
        self.bp = Blueprint("auth", __name__, url_prefix="/api/v1/auth")
        self._register_routes()

    def _register_routes(self):
        """Register authentication routes."""
        self.bp.add_url_rule("/login", view_func=self.login, methods=["POST"])
        self.bp.add_url_rule("/register", view_func=self.register, methods=["POST"])
        self.bp.add_url_rule("/refresh", view_func=self.refresh_token, methods=["POST"])
        self.bp.add_url_rule("/logout", view_func=self.logout, methods=["POST"])
        # GET, because this is the URL in a mail message and what a person
        # does with it is click it. That is a state change behind a GET,
        # which is a real cost: mail scanners that follow links will spend
        # the token before its owner does, and the owner then sees an
        # invalid link. The alternative -- a page with a button -- is a
        # better answer and a larger one; noted rather than pretended away.
        self.bp.add_url_rule("/verify", view_func=self.verify_email, methods=["GET"])
        self.bp.add_url_rule(
            "/resend-verification",
            view_func=self.resend_verification,
            methods=["POST"],
        )

    # ------------------------------------------------------------------
    # POST /api/v1/auth/login
    # ------------------------------------------------------------------
    def login(self):
        """
        Authenticate user and return access/refresh tokens.

        Reads JSON body with ``email`` and ``password``. Both tokens are
        returned in the body and also set as cookies: browsers use the
        cookies and never touch the body's refresh token, while programmatic
        clients keep no cookie jar and need the body to be able to refresh
        at all.

        Returns:
            JSON response containing ``access_token``, ``refresh_token``
            and ``user`` details.
        """
        email, password = _read_credentials()
        if not email or not password:
            raise ValidationError("Email and password are required")

        context = create_request_context()
        try:
            result = self.login_use_case.execute(email, password, context)
        except ValidationError:
            # A malformed email is a malformed request, not a refused one.
            # ValidationError is a DomainError, so the branch below used to
            # take it and answer 401 -- the same status as a wrong password,
            # for an input the same class of error is reported as 400 for
            # everywhere else in the API. Left to the global handler, which
            # is where every other ValidationError is answered.
            raise
        except DomainError as e:
            # Only domain failures carry a message meant for the client.
            # Anything else propagates to the global error handler, which
            # logs it and answers with a generic 500 instead of leaking
            # internal exception text.
            #
            # Answered here rather than re-raised because the status is the
            # endpoint's, not the code's: the handler maps some of these to
            # 403, and 403 against 401 tells an unauthenticated caller that
            # the account exists. That mapping still exists for
            # ACCOUNT_INACTIVE, which nothing raises any more -- login
            # answers INVALID_CREDENTIALS for a deactivated account -- and
            # it would catch EMAIL_NOT_VERIFIED the same way. The envelope
            # is the handler's all the same.
            return error_response(e.code, e.message, 401)

        # Build the response with access token in body and refresh token in HttpOnly cookie.
        resp = make_response(jsonify({
            "access_token": result.access_token,
            "refresh_token": result.refresh_token,
            "user": {
                "id": result.user.id,
                "email": result.user.email,
                "roles": result.user.roles,
                "is_active": result.user.is_active
            }
        }), 200)

        cookie_secure = current_app.config.get("COOKIE_SECURE", False)

        resp.set_cookie(
            key="refresh_token",
            value=result.refresh_token,
            httponly=True,
            secure=cookie_secure,
            samesite="Strict",
            max_age=_refresh_cookie_max_age(),
            path="/"
        )
        resp.set_cookie(
            key="access_token",
            value=result.access_token,
            httponly=True,
            secure=cookie_secure,
            samesite="Strict",
            max_age=_access_cookie_max_age(),
            path="/"
        )
        # The browser authenticates with cookies, so every write it makes
        # needs a CSRF token to go with them. The token is bound to this
        # user, so logging in as someone else replaces it.
        set_csrf_cookie(
            resp,
            secure=cookie_secure,
            token=build_csrf_token(
                current_app.config.get("SECRET_KEY", ""), result.user.id
            ),
        )
        return resp

    # ------------------------------------------------------------------
    # POST /api/v1/auth/register
    # ------------------------------------------------------------------
    def register(self):
        """
        Create a new user account with default role.

        Expects JSON with ``email`` and ``password``. Answers 202 whether
        the address was free or already registered, with one sentence
        that fits both -- OWASP's Authentication Cheat Sheet gives the
        shape under *Account creation*, where "This user ID is already in
        use." and "Welcome! You have signed up successfully." are both
        listed as incorrect responses.

        202 rather than 201 because 201 promises something was created,
        and on the taken-address path nothing was. Nothing identifying
        comes back either: an ``id`` here would name an account the caller
        may not own, which is the disclosure the rest of this was for. A
        client that needs the account signs in for it.

        Returns:
            202 for either outcome, 400 if the address or the password is
            refused on its own merits.
        """
        email, password = _read_credentials()
        if not email or not password:
            raise ValidationError("Email and password are required")

        context = create_request_context()
        try:
            self.register_use_case.execute(email, password, context)
            return jsonify({
                "message": (
                    "If that address can be registered, a link has been "
                    "sent to it."
                )
            }), 202
        except DomainError as e:
            # Same rule as login: internal failures must not reach the
            # client, and the status is the endpoint's rather than the
            # code's.
            return error_response(e.code, e.message, 400)

    # ------------------------------------------------------------------
    # GET /api/v1/auth/verify
    # ------------------------------------------------------------------
    def verify_email(self):
        """
        Confirm an address from the link that was mailed to it.

        Reads the token from the query string. Answers the same for every
        way a token can fail -- unknown, spent, expired, or naming an
        account that is gone -- because telling them apart would make this
        route say whether an address is registered.

        Returns:
            200 on success, 400 otherwise.
        """
        token = request.args.get("token")
        if not isinstance(token, str) or not token:
            raise ValidationError(
                "This confirmation link is not valid", field="token"
            )

        context = create_request_context()
        self.verify_email_use_case.execute(token, context)

        return jsonify({"message": "Email confirmed. You can sign in now."}), 200

    # ------------------------------------------------------------------
    # POST /api/v1/auth/resend-verification
    # ------------------------------------------------------------------
    def resend_verification(self):
        """
        Send a fresh confirmation message for an address.

        Answers identically whether the address is registered, already
        confirmed, or unknown. OWASP's Authentication Cheat Sheet gives
        this shape for the neighbouring case: "If that email address is in
        our database, we will send you an email to reset your password."
        A route that mails on request and answers honestly is a route that
        confirms who is registered.

        Returns:
            202, always, unless the address is not an address.
        """
        data = _decoded_body()
        email = data.get("email") if isinstance(data, dict) else None
        if not isinstance(email, str) or not email:
            raise ValidationError("Email is required", field="email")

        context = create_request_context()
        self.resend_verification_use_case.execute(email, context)

        return jsonify({
            "message": (
                "If that address needs confirming, a link has been sent to it."
            )
        }), 202

    # ------------------------------------------------------------------
    # POST /api/v1/auth/logout
    # ------------------------------------------------------------------
    def logout(self):
        """
        End the session and clear the authentication cookies.

        The session is revoked server-side, so deleting the cookies is not
        the only thing standing between a copied token and the account --
        the access tokens issued for this session stop working too. Only
        this session ends; the user's other devices stay signed in.

        Works for a client that has only an access token: that token names
        its session, so no refresh token is needed to end it.
        """
        refresh_token = _read_refresh_token()
        if refresh_token:
            self.authentication_service.revoke_refresh_token(refresh_token)
        elif g.get("auth_session_id"):
            self.authentication_service.revoke_session_chain(
                g.get("auth_session_id")
            )

        resp = jsonify({"message": "Logged out"})
        resp.delete_cookie('refresh_token', path='/')
        resp.delete_cookie('access_token', path='/')
        resp.delete_cookie(CSRF_COOKIE_NAME, path='/')
        return resp, 200

    # ------------------------------------------------------------------
    # POST /api/v1/auth/refresh
    # ------------------------------------------------------------------
    def refresh_token(self):
        """
        Exchange a refresh token for a fresh pair.

        The token is taken from the HttpOnly cookie, or from a
        ``refresh_token`` field in the body for clients that keep no cookie
        jar. Both new tokens are returned in the body and written back into
        the cookies, which is what the browser-facing pages authenticate
        with.

        Returns:
            JSON with ``access_token`` and ``refresh_token`` on success,
            401 otherwise.
        """
        refresh_token = _read_refresh_token()
        if not refresh_token:
            return error_response(
                "UNAUTHENTICATED", "No refresh token", 401
            )

        tokens = self.authentication_service.refresh_access_token(refresh_token)
        if not tokens:
            resp, status = error_response(
                "UNAUTHENTICATED", "Invalid or expired refresh token", 401
            )
            resp.delete_cookie("refresh_token", path="/")
            resp.delete_cookie("access_token", path="/")
            resp.delete_cookie(CSRF_COOKIE_NAME, path="/")
            return resp, status

        cookie_secure = current_app.config.get("COOKIE_SECURE", False)
        resp = make_response(jsonify({
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
        }), 200)
        resp.set_cookie(
            key="access_token",
            value=tokens.access_token,
            httponly=True,
            secure=cookie_secure,
            samesite="Strict",
            max_age=_access_cookie_max_age(),
            path="/"
        )
        # The refresh token is rotated, so the cookie has to carry the new
        # one: the old value is spent and would be read as a replay.
        resp.set_cookie(
            key="refresh_token",
            value=tokens.refresh_token,
            httponly=True,
            secure=cookie_secure,
            samesite="Strict",
            max_age=_refresh_cookie_max_age(),
            path="/"
        )
        return resp
