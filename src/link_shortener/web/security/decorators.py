"""
Authorization decorators for Flask view functions.

Provides decorators that enforce authentication and permission checks.
"""

import functools

from flask import g, jsonify, redirect, request, url_for

from link_shortener.domain import DomainError
from link_shortener.web.security.context import get_current_domain_user


def require_permission(permission: str):
    """
    Decorator that ensures the current user has a specific permission.

    If the user is not authenticated or lacks the required permission,
    a ``DomainError`` with code ``FORBIDDEN`` is raised.

    Args:
        permission: Permission string (e.g., ``"link:create"``).

    Usage::

        @require_permission("admin:manage_users")
        def create_user():
            ...
    """
    def decorator(view_func):
        @functools.wraps(view_func)
        def wrapper(*args, **kwargs):
            user = get_current_domain_user()
            authorization_service = g.get('authorization_service')

            if authorization_service is None:
                raise RuntimeError("AuthorizationService not found in g.authorization_service")

            if not authorization_service.is_allowed(user, permission):
                raise DomainError("Not authorized", code="FORBIDDEN")

            return view_func(*args, **kwargs)
        return wrapper
    return decorator


def login_required(view_func):
    """
    Decorator that enforces authentication.

    For API routes (``/api/*``), returns a 401 JSON response.
    For HTML frontend routes, redirects to the login page.
    """
    @functools.wraps(view_func)
    def wrapper(*args, **kwargs):
        if not g.get('current_user'):
            if request.path.startswith('/api/'):
                return jsonify({"error": "Authentication required"}), 401
            return redirect(url_for('frontend.login_page'))
        return view_func(*args, **kwargs)
    return wrapper
