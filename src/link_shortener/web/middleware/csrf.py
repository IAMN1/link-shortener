"""
CSRF protection for cookie-authenticated requests.

Three checks, applied together to every state-changing request that
authenticates by cookie:

1. **Double submit.** The token lives in a readable (non-HttpOnly) cookie and
   must be echoed in the ``X-CSRF-Token`` header. A cross-site attacker can
   make the browser send cookies but can neither read them nor set a custom
   header, so the two values match only on a genuine same-origin request.
2. **Signature.** The token is an HMAC over the user it was issued to, keyed
   with ``SECRET_KEY``. Plain double submit accepts any value as long as the
   two copies agree, so anyone able to write a cookie on the domain -- script
   on a sibling subdomain, or a network position while cookies travel over
   plain HTTP -- could plant a known value and satisfy the check. A signed
   token cannot be produced without the key.
3. **Origin.** When the browser states an origin, it must be one we serve.
   This is what stops the planted-cookie case from a sibling subdomain:
   cookies do not distinguish subdomains, ``Origin`` does. It is skipped when
   neither ``Origin`` nor ``Referer`` is present, since proxies strip them and
   the signed token still has to check out.

The whole thing applies only to requests that rely on cookies. A client
authenticating with a **valid** ``Authorization: Bearer <token>`` has already
proven it can set request headers and is not exposed to CSRF; those requests
pass through untouched so programmatic API clients keep working.

Three rules keep that exemption honest, and all three are the same rule:
decide from the layer that knows, not from something that resembles the
answer.

- The exemption is granted on the credential the authentication layer
  actually accepted (``g.auth_token_source``), never on the shape of the
  incoming header -- an empty or garbage ``Bearer`` token authenticates
  nothing.
- It never applies to endpoints that read an auth cookie themselves, listed
  in ``COOKIE_AUTHORITY_ENDPOINTS``, because their authority comes from the
  cookie regardless of any header.
- The token is bound to, and verified against, the owner of the *cookies* --
  not ``g.current_user``, which on those same endpoints can be whoever a
  foreign ``Bearer`` header authenticated.
"""

import hashlib
import hmac
import secrets
import time
from typing import Optional
from urllib.parse import urlparse

from flask import Flask, g, request
from flask_babel import gettext

from link_shortener.application import AuthenticationService, Logger
from link_shortener.web.middleware.authentication import AUTH_SOURCE_HEADER
from link_shortener.web.responses import error_response
from link_shortener.web.middleware.hooks import response_hook


CSRF_COOKIE_NAME = "csrf_token"
"""Name of the readable cookie holding the CSRF token."""

CSRF_HEADER_NAME = "X-CSRF-Token"
"""Request header the client must echo the CSRF token in."""

CSRF_COOKIE_MAX_AGE = 7 * 24 * 3600
"""Lifetime of the CSRF cookie, matching the refresh token cookie."""

CSRF_TOKEN_TTL_SECONDS = 12 * 3600
"""
How long a minted token stays acceptable.

Shorter than the cookie that carries it: an aged-out token is replaced on
the next response rather than stranding the session, so the cookie outliving
the token costs nothing while bounding how long a leaked value is worth
anything.
"""

AUTH_COOKIE_NAMES = ("access_token", "refresh_token")
"""Cookies that authenticate a request and therefore require CSRF cover."""

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
"""Methods that do not change state and need no CSRF token."""

COOKIE_AUTHORITY_ENDPOINTS = frozenset({"auth.refresh_token", "auth.logout"})
"""
Endpoints that read an auth cookie themselves instead of acting as the
authenticated user.

Their authority comes from the cookie whatever the headers say, so the
header exemption below must never apply to them. Any new endpoint that
reads ``request.cookies`` directly belongs in this set.
"""


def _signature(secret_key: str, user_id: str, nonce: str, issued_at: int) -> str:
    """
    Compute the HMAC binding a nonce and an issue time to a user.

    Args:
        secret_key: Application signing key.
        user_id: User the token is issued to.
        nonce: Random part of the token.
        issued_at: Unix timestamp the token was minted at.

    Returns:
        Hex-encoded HMAC-SHA256.
    """
    message = f"{user_id}:{nonce}:{issued_at}".encode("utf-8")
    return hmac.new(
        secret_key.encode("utf-8"), message, hashlib.sha256
    ).hexdigest()


def build_csrf_token(secret_key: str, user_id: str) -> str:
    """
    Mint a CSRF token for a user.

    Args:
        secret_key: Application signing key.
        user_id: User the token is issued to.

    Returns:
        Token of the form ``<nonce>.<issued_at>.<signature>``.
    """
    nonce = secrets.token_urlsafe(16)
    issued_at = int(time.time())
    return f"{nonce}.{issued_at}.{_signature(secret_key, user_id, nonce, issued_at)}"


def verify_csrf_token(secret_key: str, user_id: str, token: str) -> bool:
    """
    Check that a token was issued by this service to this user, recently.

    The issue time is inside the signed message, so it cannot be pushed
    forward by whoever holds the token: a leaked value stops working once
    ``CSRF_TOKEN_TTL_SECONDS`` have passed rather than lasting forever.

    Args:
        secret_key: Application signing key.
        user_id: User the request is acting as.
        token: Token presented by the client.

    Returns:
        True if the signature matches and the token has not aged out.
    """
    parts = token.split(".")
    if len(parts) != 3:
        return False

    nonce, raw_issued_at, signature = parts
    if not nonce or not signature:
        return False

    try:
        issued_at = int(raw_issued_at)
    except ValueError:
        return False

    if int(time.time()) - issued_at > CSRF_TOKEN_TTL_SECONDS:
        return False

    expected = _signature(secret_key, user_id, nonce, issued_at)
    # Compared as bytes: compare_digest rejects str holding non-ASCII, which
    # would turn a forged token into a 500 instead of a refusal.
    return hmac.compare_digest(
        signature.encode("utf-8"), expected.encode("utf-8")
    )


def set_csrf_cookie(response, secure: bool, token: str):
    """
    Attach a CSRF cookie to a response.

    The cookie is deliberately **not** HttpOnly: the frontend has to read it
    to build the ``X-CSRF-Token`` header. That is safe, because the token
    protects against cross-site requests, not against scripts already
    running on this origin.

    Args:
        response: Flask response to attach the cookie to.
        secure: Whether to set the Secure flag (HTTPS only).
        token: The token to store.

    Returns:
        The response, for chaining.
    """
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        httponly=False,
        secure=secure,
        samesite="Strict",
        max_age=CSRF_COOKIE_MAX_AGE,
        path="/",
    )
    return response


LOOPBACK_TWINS = {"localhost": "127.0.0.1", "127.0.0.1": "localhost"}
"""The two spellings of this machine, each naming the other.

A browser treats them as different origins; a person treats them as the
same address and types whichever they remember.
"""


def _loopback_twin(parsed) -> set:
    """
    The other spelling of a loopback base URL, if that is what this is.

    ``.env.example`` lists both spellings of the loopback address at port
    5000, and says why: "someone who opened `http://127.0.0.1:5000` sees a
    working front page (an anonymous caller does not go through CSRF) and
    'CSRF token missing or invalid' on every form the moment they sign in
    -- measured on a live run".

    That fix was pinned to the port. The guide tells a reader to move the
    published port when 5000 is taken, and moving it puts the failure
    back: measured on a stack published at 5101, `http://localhost:5101`
    wrote fine and `http://127.0.0.1:5101` answered 403
    `CSRF_TOKEN_INVALID` on every signed-in form -- including the logout,
    which failed silently and left the dashboard open. Meanwhile the two
    stale entries for 5000, where nothing is listening, were still
    admitted.

    Derived from ``BASE_URL`` rather than added to the template, so it
    follows the port instead of naming one. Only for loopback: a
    deployment names a real ``DOMAIN`` -- both deployed profiles refuse to
    start without one -- and nothing here widens anything for it.

    Args:
        parsed: The parsed ``BASE_URL``.

    Returns:
        A set holding the twin origin, or an empty one.
    """
    host = parsed.hostname or ""
    twin = LOOPBACK_TWINS.get(host)
    if not twin:
        return set()

    port = f":{parsed.port}" if parsed.port else ""
    return {f"{parsed.scheme}://{twin}{port}"}


class CsrfProtectionMiddleware:
    """
    Rejects state-changing requests that are authenticated by cookie but
    carry no valid CSRF token.

    Also issues a token to any cookie-authenticated request that does not
    have one yet, so that sessions established before this middleware
    existed recover on their next page load instead of failing on the next
    write.
    """

    def __init__(
        self,
        app: Flask,
        logger: Logger,
        authentication_service: AuthenticationService,
    ):
        """
        Args:
            app: Flask application instance.
            logger: Application logger.
            authentication_service: Used to read the identity out of the
                refresh cookie when the access token has already expired.
        """
        self.app = app
        self.logger = logger
        self.authentication_service = authentication_service
        self.cookie_secure = app.config.get("COOKIE_SECURE", False)
        self.secret_key = app.config.get("SECRET_KEY", "")
        self.allowed_origins = self._build_allowed_origins(app)
        self._register_handlers()

    @staticmethod
    def _build_allowed_origins(app: Flask) -> frozenset:
        """
        Collect the origins a browser may legitimately post from.

        Args:
            app: Flask application instance.

        Returns:
            Set of ``scheme://host[:port]`` strings.
        """
        origins = set()
        for value in app.config.get("CORS_ORIGINS", []) or []:
            origins.add(value.rstrip("/"))

        base_url = app.config.get("BASE_URL")
        if base_url:
            parsed = urlparse(base_url)
            if parsed.scheme and parsed.netloc:
                origins.add(f"{parsed.scheme}://{parsed.netloc}")
                origins.update(_loopback_twin(parsed))

        return frozenset(origins)

    def _is_cookie_authenticated(self) -> bool:
        """
        Report whether the current request relies on cookies to authenticate.

        The exemption is decided by what ``AuthenticationMiddleware``
        actually used, never by the shape of the incoming header: a header
        that merely looks like a Bearer credential (``"Bearer "`` with an
        empty token) still falls back to the cookie, and reading the header
        here would grant that request an exemption it has not earned.

        Returns:
            True if the request carries an auth cookie that was not
            superseded by a validated header credential.
        """
        has_auth_cookie = any(
            request.cookies.get(name) for name in AUTH_COOKIE_NAMES
        )

        # For these the cookie *is* the credential, so a header says nothing
        # about where the request's authority comes from.
        if request.endpoint in COOKIE_AUTHORITY_ENDPOINTS:
            return has_auth_cookie

        if g.get("auth_token_source") == AUTH_SOURCE_HEADER:
            return False

        return has_auth_cookie

    def _resolve_user_id(self) -> Optional[str]:
        """
        Identify the owner of the cookie session.

        Deliberately reads the cookies rather than ``g.current_user``: this
        token guards cookie authority, so it must be bound to whoever the
        cookies belong to. On an endpoint from
        ``COOKIE_AUTHORITY_ENDPOINTS`` a request can carry someone else's
        valid Bearer header alongside the victim's cookies, and taking the
        identity from the header would let that someone present a token
        signed for themselves -- or, on the reissue path, overwrite the
        victim's token with one bound to the attacker.

        The refresh cookie is the fallback because ``/auth/refresh`` is
        reached precisely when the access token has run out.

        Returns:
            User id, or None if the cookies resolve to nobody.
        """
        for cookie_name, token_type in (
            ("access_token", "access"),
            ("refresh_token", "refresh"),
        ):
            token = request.cookies.get(cookie_name)
            if not token:
                continue

            payload = self.authentication_service.validate_token(
                token, expected_type=token_type
            )
            if payload:
                return payload.get("sub")

        return None

    def _origin_is_allowed(self) -> bool:
        """
        Check the browser-stated origin against the allow-list.

        Returns:
            True if no origin was stated, or if the stated one is allowed.
        """
        origin = request.headers.get("Origin")
        if not origin:
            referer = request.headers.get("Referer")
            if not referer:
                # Nothing stated. Proxies do strip these, so the signed token
                # is left to carry the request on its own.
                return True
            parsed = urlparse(referer)
            if not parsed.scheme or not parsed.netloc:
                return False
            origin = f"{parsed.scheme}://{parsed.netloc}"

        return origin.rstrip("/") in self.allowed_origins

    def _register_handlers(self):
        """Install the ``before_request`` and ``after_request`` hooks."""

        @self.app.before_request
        def enforce_csrf():
            """Block unsafe cookie-authenticated requests without a token."""
            if request.method in SAFE_METHODS:
                return

            if not self._is_cookie_authenticated():
                return

            if not self._origin_is_allowed():
                self.logger.warning(
                    "Cross-origin write rejected",
                    path=request.path,
                    method=request.method,
                    origin=request.headers.get("Origin"),
                )
                return self._refuse()

            cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
            header_token = request.headers.get(CSRF_HEADER_NAME)
            if not cookie_token or not header_token:
                return self._refuse()

            if not hmac.compare_digest(
                cookie_token.encode("utf-8"), header_token.encode("utf-8")
            ):
                return self._refuse()

            user_id = self._resolve_user_id()
            if not user_id:
                return self._refuse()

            if not verify_csrf_token(self.secret_key, user_id, cookie_token):
                return self._refuse()

        @self.app.after_request
        @response_hook(self.logger)
        def issue_csrf_cookie(response):
            """Hand out a CSRF cookie when a cookie session lacks one."""
            if request.path.startswith("/static/"):
                return response

            # Leave the response alone if it already decides this cookie's
            # fate itself -- login sets it, logout clears it.
            if any(
                header.startswith(f"{CSRF_COOKIE_NAME}=")
                for header in response.headers.getlist("Set-Cookie")
            ):
                return response

            has_auth_cookie = any(
                request.cookies.get(name) for name in AUTH_COOKIE_NAMES
            )
            if not has_auth_cookie:
                return response

            user_id = self._resolve_user_id()
            if not user_id:
                return response

            # Replace a token that no longer checks out, not just a missing
            # one. A cookie left over from another account or from an older
            # token format would otherwise fail verification on every write
            # while never being renewed, stranding the session in 403.
            existing = request.cookies.get(CSRF_COOKIE_NAME)
            if existing and verify_csrf_token(self.secret_key, user_id, existing):
                return response

            set_csrf_cookie(
                response,
                secure=self.cookie_secure,
                token=build_csrf_token(self.secret_key, user_id),
            )

            return response

    def _refuse(self):
        """
        Build the refusal returned for every failed check.

        The sentence is written for whoever is reading it and taken from
        the catalogue, like every other sentence this service shows. Built
        by hand it was "CSRF token missing or invalid" -- the name of the
        mechanism rather than anything a visitor can act on, and English
        on a page the same request had just been answered in Russian.
        What a person can act on is reloading: the ordinary cause is a
        token that aged out under a form left open, and the next response
        hands out a fresh one.

        The envelope is ``error_response`` rather than an ``ErrorResponse``
        assembled here, for the reason the throttle's 429 was moved onto
        it: an answer built by hand is a second shape for one API, and it
        drifts the first time the envelope gains a field.

        There is deliberately no page branch. ``wants_html`` decides that
        question everywhere else, and here it has nothing to decide: this
        check only ever refuses an unsafe method, and every route in the
        application that takes one is under ``/api/``. A page branch would
        be a branch no request can reach.

        Returns:
            Tuple of (JSON response, 403).
        """
        # The mechanism's own words, not the shown ones: an operator
        # matching this against the middleware needs the name of the check
        # that failed, and this line is not read by the visitor.
        self.logger.warning(
            "CSRF token missing or invalid",
            path=request.path,
            method=request.method,
        )

        return error_response(
            "CSRF_TOKEN_INVALID",
            gettext(
                "This request could not be verified. Reload the page and "
                "try again."
            ),
            403,
        )
