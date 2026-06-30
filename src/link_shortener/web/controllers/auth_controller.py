"""
Authentication controller -- /api/v1/auth/* endpoints.

Handles login, registration, token refresh, and logout.
"""

from flask import Blueprint, current_app, jsonify, make_response, request

from link_shortener.application import AuthenticationService, LoginUseCase, RegisterUseCase
from link_shortener.web.security.context import create_request_context


class AuthController:
    """
    Controller for authentication endpoints (login, token refresh, logout, register).
    """

    def __init__(
        self, 
        authentication_service: AuthenticationService,
        login_use_case: LoginUseCase,
        register_use_case: RegisterUseCase
    ):
        self.authentication_service = authentication_service
        self.login_use_case = login_use_case
        self.register_use_case = register_use_case
        self.bp = Blueprint("auth", __name__, url_prefix="/api/v1/auth")
        self._register_routes()

    def _register_routes(self):
        """Register authentication routes."""
        self.bp.add_url_rule("/login", view_func=self.login, methods=["POST"])
        self.bp.add_url_rule("/register", view_func=self.register, methods=["POST"])
        self.bp.add_url_rule("/refresh", view_func=self.refresh_token, methods=["POST"])
        self.bp.add_url_rule("/logout", view_func=self.logout, methods=["POST"])

    # ------------------------------------------------------------------
    # POST /api/v1/auth/login
    # ------------------------------------------------------------------
    def login(self):
        """
        Authenticate user and return access/refresh tokens.

        Reads JSON body with ``email`` and ``password``.
        On success, the refresh token is stored in an HttpOnly cookie.

        Returns:
            JSON response containing ``access_token`` and ``user`` details.
        """
        data = request.get_json() or {}
        email = data.get("email")
        password = data.get("password")
        if not email or not password:
            return jsonify({"error": "Email and password are required"}), 400

        context = create_request_context()
        try:
            result = self.login_use_case.execute(email, password, context)
        except Exception as e:
            return jsonify({"error": str(e)}), 401

        # Build the response with access token in body and refresh token in HttpOnly cookie.
        resp = make_response(jsonify({
            "access_token": result.access_token,
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
            max_age=7 * 24 * 3600,
            path="/"
        )
        resp.set_cookie(
            key="access_token",
            value=result.access_token,
            httponly=True,
            secure=cookie_secure,
            samesite="Strict",
            max_age=15 * 60,
            path="/"
        )
        return resp

    # ------------------------------------------------------------------
    # POST /api/v1/auth/register
    # ------------------------------------------------------------------
    def register(self):
        """
        Create a new user account with default role.

        Expects JSON with ``email`` and ``password``.
        Returns 201 on success, 400 if validation fails.
        """
        data = request.get_json() or {}
        email = data.get("email")
        password = data.get("password")
        if not email or not password:
            return jsonify({"error": "Email and password are required"}), 400

        context = create_request_context()
        try:
            result = self.register_use_case.execute(email, password, context)
            return jsonify({
                "message": "User registered successfully",
                "user": {
                    "id": result.id,
                    "email": result.email,
                    "roles": result.roles,
                    "is_active": result.is_active
                }
            }), 201
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    # ------------------------------------------------------------------
    # POST /api/v1/auth/logout
    # ------------------------------------------------------------------
    def logout(self):
        """Clear the refresh token cookie and confirm logout."""
        resp = jsonify({"message": "Logged out"})
        resp.delete_cookie('refresh_token', path='/')
        resp.delete_cookie('access_token', path='/')
        return resp, 200

    # ------------------------------------------------------------------
    # POST /api/v1/auth/refresh
    # ------------------------------------------------------------------
    def refresh_token(self):
        """
        Issue a new access token using a valid refresh token cookie.

        Returns:
            JSON with ``access_token`` on success, 401 otherwise.
        """
        refresh_token = request.cookies.get("refresh_token")
        if not refresh_token:
            return jsonify({"error": "No refresh token"}), 401

        new_access_token = self.authentication_service.refresh_access_token(refresh_token)
        if not new_access_token:
            resp = jsonify({"error": "Invalid or expired refresh token"})
            resp.delete_cookie("refresh_token")
            return resp, 401

        return jsonify({"access_token": new_access_token}), 200
