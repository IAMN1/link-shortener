"""
Authorization decorators for Flask view functions.

Provides decorators that enforce authentication and permission checks.
"""

import functools

from flask import g, redirect, request, url_for

from link_shortener.domain import DomainError
from link_shortener.web.security.context import get_current_domain_user


def require_permission(permission: str):
    """
    Decorator that ensures the current caller has a specific permission.

    A caller who lacks the permission is refused with a ``DomainError``:
    ``UNAUTHENTICATED`` (401) if nobody is logged in, ``FORBIDDEN`` (403)
    otherwise -- one answer for both would leave a client unable to tell
    "log in" from "logging in will not help".

    Anonymous callers are not refused outright -- they act under the
    ``guest`` role, so a permission that role grants passes here.

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
                # Asked after the permission check, not before: what the
                # caller is missing decides which refusal is truthful.
                if user is None:
                    raise DomainError(
                        "Authentication required", code="UNAUTHENTICATED"
                    )
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
                # Raised rather than answered here, as `require_permission`
                # beside it does: the error handler is the one place that
                # turns a code into a status and an ErrorResponse, and an
                # answer built by hand here was the API's only 401 outside
                # that envelope.
                raise DomainError(
                    "Authentication required", code="UNAUTHENTICATED"
                )
            return redirect(url_for('frontend.login_page'))
        return view_func(*args, **kwargs)
    return wrapper
