from flask import Blueprint, current_app, jsonify, make_response, request
from link_shortener.application import AuthenticationService
from link_shortener.web.security.context import create_request_context


class AuthController:
    """
    Controller for authentication endpoints (login, token refresh, logout).
    
    Handles ``/api/v1/auth/*`` routes and uses the authentication service to 
        issue and validate JWT tokens.
    """

    def __init__(self, auth_service: AuthenticationService):
        self.auth_service = auth_service

        self.bp = Blueprint("auth", __name__, url_prefix="/api/v1/auth")
        self.bp.add_url_rule("/logout", view_func=self.logout, methods=["POST"])
        self._register_routes()
    

    def _register_routes(self):
        """Register authentication routes."""
        self.bp.add_url_rule("/login", view_func=self.login, methods=["POST"])
        self.bp.add_url_rule("/refresh", view_func=self.refresh_token, methods=["POST"])
    
    def login(self):
        """
        Authenticate user and return access/refresh tokens.

        Reads JSON body with ``email`` and ``password``.
        On success, the refresh token is stored in an HttpOnly cookie.

        Returns:
            JSON response containing ``access_token`` and ``user`` details.
        """
        data = request.get_json()
        email = data.get("email")
        password = data.get("password")
        if not email or not password:
            return jsonify({"error": "Email and password are required"}), 400

        container = current_app.container
        login_uc = container.get_login_use_case()
        context = create_request_context()
        try:
            result = login_uc.execute(email, password, context)
        except Exception as e:
            return jsonify({"error": str(e)}), 401

        # Создаём ответ с access-токеном в теле и refresh-токеном в HttpOnly куке
        resp = make_response(jsonify({
            "access_token": result.access_token,
            "user": {
                "id": result.user.id,
                "email": result.user.email,
                "roles": result.user.roles,
                "is_active": result.user.is_active
            }
        }), 200)
        resp.set_cookie(
            key="refresh_token",
            value=result.refresh_token,
            httponly=True,
            secure=False,               # set to True in production
            samesite="Strict",
            max_age=7 * 24 * 3600,      # 7 days
            path="/"
        )
        return resp

    def logout(self):
        """Clear the refresh token cookie and confirm logout."""
        resp = jsonify({"message": "Logged out"})
        resp.delete_cookie('refresh_token', path='/')
        return resp, 200

    def refresh_token(self):
        """
        Issue a new access token using a valid refresh token cookie.

        Returns:
            JSON with ``access_token`` on success, 401 otherwise.
        """
        refresh_token = request.cookies.get("refresh_token")
        if not refresh_token:
            return jsonify({"error": "No refresh token"}), 401

        new_access_token = self.auth_service.refresh_access_token(refresh_token)
        if not new_access_token:
            resp = jsonify({"error": "Invalid or expired refresh token"})
            resp.delete_cookie("refresh_token")
            return resp, 401

        return jsonify({"access_token": new_access_token}), 200
