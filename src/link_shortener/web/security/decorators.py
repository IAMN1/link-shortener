"""
Authorization decorators for Flask view functions.

Provides decorators that enforce authentication and permission checks.
"""

import functools

from flask import current_app, g, redirect, url_for

from link_shortener.application import AuthorizationService
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
            auth_service: AuthorizationService = current_app.container.get_authorization_service()
            if not auth_service.is_allowed(user, permission):
                raise DomainError("Not authorized", code="FORBIDDEN")
            return view_func(*args, **kwargs)
        return wrapper
    return decorator


def login_required(view_func):
    """
    Decorator that redirects to the login page if the user is not authenticated.

    Intended for HTML frontend routes (admin panel). If ``g.current_user``
    is not set, a redirect to ``admin_frontend.login_page`` is returned.

    Usage::

        @login_required
        def dashboard():
            return render_template('admin/dashboard.html')
    """
    @functools.wraps(view_func)
    def wrapper(*args, **kwargs):
        if not g.get('current_user'):
            return redirect(url_for('admin_frontend.login_page'))
        return view_func(*args, **kwargs)
    return wrapper
