"""
Authentication controller -- /api/v1/auth/* endpoints.

Handles login, registration, token refresh, and logout.
"""

from typing import Optional

from flask import Blueprint, current_app, g, jsonify, make_response, request
from flask_babel import gettext

from link_shortener.application import AuthService
from link_shortener.domain import DomainError, ValidationError
from link_shortener.web.middleware.csrf import (
    CSRF_COOKIE_NAME, build_csrf_token, set_csrf_cookie
)
from link_shortener.web.middleware.error_handler import client_message
from link_shortener.web.request_body import json_object, optional_json_object
from link_shortener.web.schemas.auth import (
    MessageResponse, RefreshResponse, RegisterResponse, TokenPairResponse,
    UserResponse,
)
from link_shortener.web.responses import error_response
from link_shortener.web.security.context import create_request_context
from link_shortener.web.security.decorators import login_required
from link_shortener.domain.i18n import N_


def _read_credentials():
    """
    Pull ``email`` and ``password`` out of the request body.

    Guards the contents of the body; its shape and its decoding are
    ``web/request_body.py``'s, which is where the whole application reads
    a body now. This controller used to carry a reader of its own, and the
    two disagreed about one and the same request: a body too deeply nested
    to decode was reported here as credentials nobody sent.

    Returns:
        Tuple of (email, password), or (None, None) if the body does not
        carry usable credentials.
    """
    data = json_object()

    email = data.get("email")
    password = data.get("password")
    if not isinstance(email, str) or not isinstance(password, str):
        return None, None

    return email or None, password or None


def _read_refresh_token() -> Optional[str]:
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

    # The lenient reader: this route is reached without a body at all
    # by every browser, which keeps its token in the cookie read above.
    token = optional_json_object().get("refresh_token")
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


def _set_token_cookies(resp, access_token: str, refresh_token: str) -> None:
    """
    Write both authentication cookies onto a response.

    One place rather than three. Sign-in, refresh and the password change
    all hand the browser the same pair under the same flags, and the flags
    are the security of the scheme: a ``samesite`` or an ``httponly``
    dropped from one copy is a hole in one route that reads exactly like
    the two beside it.

    Args:
        resp: The response to write the cookies onto.
        access_token: Freshly issued access token.
        refresh_token: Freshly issued refresh token. Rotated on every
            issue, so the cookie always carries the newest one -- an
            earlier value is spent and would be read as a replay.
    """
    cookie_secure = current_app.config.get("COOKIE_SECURE", False)
    resp.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=cookie_secure,
        samesite="Strict",
        max_age=_access_cookie_max_age(),
        path="/",
    )
    resp.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=cookie_secure,
        samesite="Strict",
        max_age=_refresh_cookie_max_age(),
        path="/",
    )


class AuthController:
    """
    Controller for authentication endpoints (login, token refresh, logout, register).
    """

    def __init__(self, auth_service: AuthService):
        self.auth_service = auth_service
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
        # POST is what the confirmation page sends, and it is the method
        # the act deserves: spending a token is a state change. GET stays
        # so that links mailed before the page existed still work.
        self.bp.add_url_rule(
            "/verify", view_func=self.verify_email, methods=["GET", "POST"]
        )
        self.bp.add_url_rule(
            "/resend-verification",
            view_func=self.resend_verification,
            methods=["POST"],
        )
        self.bp.add_url_rule(
            "/change-password",
            view_func=self.change_password,
            methods=["POST"],
        )
        self.bp.add_url_rule(
            "/forgot-password",
            view_func=self.forgot_password,
            methods=["POST"],
        )
        # POST only, unlike `/verify`, which still answers GET so that
        # links mailed before its page existed keep working. This one has
        # no such history and cannot acquire it: the new password does not
        # exist until somebody types it, so there is nothing a GET could
        # carry.
        self.bp.add_url_rule(
            "/reset-password",
            view_func=self.reset_password,
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
            raise ValidationError(N_("Email and password are required"))

        context = create_request_context()
        try:
            result = self.auth_service.login(email, password, context)
        except ValidationError:
            # A malformed email is a malformed request, not a refused one.
            # ValidationError is a DomainError, so without this clause the
            # branch below would answer 401 -- the status of a wrong
            # password -- where the rest of the API answers 400. Left to the
            # global handler, which answers every other ValidationError.
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
            #
            # The sentence is the handler's rule too, which is why it is
            # `client_message` rather than `translate_error`: what a code
            # may say to a client is decided by the code, and answering
            # with a status of our own must not turn a 5xx sentence about
            # the service's own state into a 401 a stranger reads.
            return error_response(e.code, client_message(e), 401)

        # Build the response with access token in body and refresh token in HttpOnly cookie.
        resp = make_response(jsonify(TokenPairResponse(
            access_token=result.access_token,
            refresh_token=result.refresh_token,
            user=UserResponse.from_dto(result.user),
        ).model_dump()), 200)

        cookie_secure = current_app.config.get("COOKIE_SECURE", False)

        _set_token_cookies(resp, result.access_token, result.refresh_token)
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
            raise ValidationError(N_("Email and password are required"))

        context = create_request_context()
        try:
            self.auth_service.register(email, password, context)
            return jsonify(RegisterResponse(message=(
                "If that address can be registered, a link has been "
                "sent to it."
            )).model_dump()), 202
        except ValidationError:
            # A refused address or a refused password is a malformed
            # request, and the global handler is what answers those --
            # with the offending field in ``details``, which this branch
            # cannot carry. Answered here, the two neighbouring routes
            # reported one and the same ``ValidationError`` in two
            # envelopes: ``/register`` with ``details: null`` and
            # ``/forgot-password`` with the field named, while the OpenAPI
            # document promises the field on both. The handler also logs
            # the refusal, which this branch never did.
            raise
        except DomainError as e:
            # Same rule as login: internal failures must not reach the
            # client, and the status is the endpoint's rather than the
            # code's. `client_message` is what keeps the first half true
            # while the second is being exercised -- the status here is
            # 400 whatever the code, so nothing else would stop a sentence
            # meant for a log from being read as a bad request.
            return error_response(e.code, client_message(e), 400)

    # ------------------------------------------------------------------
    # GET, POST /api/v1/auth/verify
    # ------------------------------------------------------------------
    def verify_email(self):
        """
        Confirm an address from the link that was mailed to it.

        Reads the token from the JSON body when the confirmation page
        sends one, and from the query string otherwise -- which is how a
        link mailed before that page existed still works. Answers the same
        for every way a token can fail -- unknown, spent, expired, or
        naming an account that is gone -- because telling them apart would
        make this route say whether an address is registered.

        Returns:
            200 on success, 400 otherwise.
        """
        token = request.args.get("token")
        if not token and request.method == "POST":
            token = json_object().get("token")
        if not isinstance(token, str) or not token:
            raise ValidationError(
                N_("This confirmation link is not valid"), field="token"
            )

        context = create_request_context()
        self.auth_service.verify_email(token, context)

        return jsonify(MessageResponse(
            message="Email confirmed. You can sign in now."
        ).model_dump()), 200

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
        email = json_object().get("email")
        if not isinstance(email, str) or not email:
            raise ValidationError(N_("Email is required"), field="email")

        context = create_request_context()
        self.auth_service.resend_verification(email, context)

        return jsonify(MessageResponse(message=(
            "If that address needs confirming, a link has been sent to it."
        )).model_dump()), 202

    # ------------------------------------------------------------------
    # POST /api/v1/auth/change-password
    # ------------------------------------------------------------------
    @login_required
    def change_password(self):
        """
        Replace the caller's own password.

        Takes ``current_password`` and ``new_password``. The account is the
        one the request is authenticated as and is never read from the
        body: an endpoint that took an id there would let anyone signed in
        change anybody's password, which is the whole authorization of this
        route in one field.

        Every session the account had is revoked, this one included, and a
        new pair is issued to the caller in the same response -- so the
        browser that made the change stays signed in and every other device
        does not. The refusals are named rather than generalised: the
        caller is already inside the account, so there is nothing left for
        a vague answer to protect, and "something was wrong" would send
        somebody to re-read a new password they typed correctly.

        Returns:
            200 with a fresh pair of tokens, 400 if the current password is
            wrong or the new one is refused, 401 if the caller is not
            signed in.
        """
        data = json_object()
        current_password = data.get("current_password")
        new_password = data.get("new_password")
        if not isinstance(current_password, str) or not current_password:
            raise ValidationError(
                N_("Current password is required"), field="current_password"
            )
        if not isinstance(new_password, str) or not new_password:
            raise ValidationError(
                N_("New password is required"), field="new_password"
            )

        context = create_request_context()
        tokens = self.auth_service.change_password(
            user_id=g.current_user.id,
            current_password=current_password,
            new_password=new_password,
            context=context,
        )

        # The same body the refresh route gives, and for the same reason:
        # what came back is a new pair. No sentence beside it -- the page
        # says what happened in the reader's own language, out of the
        # catalogue, and a second sentence here would be an English one
        # nothing displays.
        resp = make_response(jsonify(RefreshResponse(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
        ).model_dump()), 200)
        # Required, not a convenience: the access token in the browser
        # names a session this request has just revoked, so without the new
        # pair the page that made the change is signed out by it.
        _set_token_cookies(resp, tokens.access_token, tokens.refresh_token)
        return resp

    # ------------------------------------------------------------------
    # POST /api/v1/auth/forgot-password
    # ------------------------------------------------------------------
    def forgot_password(self):
        """
        Mail a password reset link to an address.

        Answers 202 with the same sentence whether the address is
        registered, unconfirmed, deactivated or unknown. OWASP's Forgot
        Password Cheat Sheet gives this response by name -- "If that email
        address is in our database, we will send you an email to reset your
        password" -- because a route that mails on request and answers
        honestly tells anyone who asks who is registered.

        Returns:
            202, always, unless the address is not an address.
        """
        email = json_object().get("email")
        if not isinstance(email, str) or not email:
            raise ValidationError(N_("Email is required"), field="email")

        context = create_request_context()
        # The outcome is deliberately dropped. Which of the three things
        # happened is what this route exists not to say; the journal has
        # it.
        self.auth_service.request_password_reset(email, context)

        return jsonify(MessageResponse(message=(
            "If that address has an account, a link to reset its "
            "password has been sent to it."
        )).model_dump()), 202

    # ------------------------------------------------------------------
    # POST /api/v1/auth/reset-password
    # ------------------------------------------------------------------
    def reset_password(self):
        """
        Set a new password from the link that was mailed.

        Takes ``token`` and ``new_password``. Answers the same for every
        way a token can fail -- unknown, spent, expired, or naming an
        account that is gone or switched off -- because telling them apart
        would make this route say whether an address is registered and
        whether somebody has already used their link.

        Nobody is signed in by this. The person goes to the sign-in page
        and uses the password they just chose, which is what OWASP asks
        for: the account was opened by a link out of a mailbox, and the
        first thing it should ask for is the credential.

        Returns:
            200 on success, 400 for a token that cannot be spent or a
            password the policy refuses.
        """
        data = json_object()
        token = data.get("token")
        new_password = data.get("new_password")
        if not isinstance(token, str) or not token:
            raise ValidationError(
                N_("This reset link is not valid"), field="token"
            )
        if not isinstance(new_password, str) or not new_password:
            raise ValidationError(
                N_("New password is required"), field="new_password"
            )

        context = create_request_context()
        self.auth_service.reset_password(token, new_password, context)

        return jsonify(MessageResponse(
            message="Password changed. You can sign in now."
        ).model_dump()), 200

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
            self.auth_service.logout(refresh_token)
        elif g.get("auth_session_id"):
            self.auth_service.logout_session(g.get("auth_session_id"))

        resp = jsonify(MessageResponse(message="Logged out").model_dump())
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
                "UNAUTHENTICATED", gettext("No refresh token"), 401
            )

        tokens = self.auth_service.refresh(refresh_token)
        if not tokens:
            resp, status = error_response(
                "UNAUTHENTICATED", gettext("Invalid or expired refresh token"), 401
            )
            resp.delete_cookie("refresh_token", path="/")
            resp.delete_cookie("access_token", path="/")
            resp.delete_cookie(CSRF_COOKIE_NAME, path="/")
            return resp, status

        resp = make_response(jsonify(RefreshResponse(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
        ).model_dump()), 200)
        _set_token_cookies(resp, tokens.access_token, tokens.refresh_token)
        return resp
