"""
Authorization decorators for Flask view functions.

Provides decorators that enforce authentication and permission checks.
"""

import functools
from typing import Any, cast

from flask import g, redirect, request, url_for

from link_shortener.domain import DomainError, PermissionDeniedError
from link_shortener.web.security.context import get_current_domain_user
from link_shortener.domain.i18n import N_


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
                        N_("Authentication required"), code="UNAUTHENTICATED"
                    )
                raise PermissionDeniedError(
                    N_("Not authorized"), required=[permission]
                )

            return view_func(*args, **kwargs)

        # The permission, left where a reader of the route table can find
        # it. The published document has to say which operations need a
        # token, and the only truthful source for that is this decorator:
        # a list kept beside it is a list that stops agreeing with it.
        # `openapi.py` reads this attribute off the view; nothing else
        # depends on it.
        # Cast because a decorated view is typed as a wrapper, which
        # declares no such attribute: the mark is data for `openapi.py`,
        # not part of the calling contract.
        cast(Any, wrapper).required_permission = permission
        return wrapper
    return decorator


def require_any_permission(*permissions: str):
    """
    Decorator for a page that several permissions each open on their own.

    Written for the journal viewer, which is one page over three journals
    read under two permissions: ``audit:view`` opens the audit journal and
    ``logs:view`` the other two, and a caller holding either has something
    to see. Guarding it with one of the two would hide the page from half
    the callers entitled to it; guarding it with neither would serve an
    empty screen to everybody.

    What it does *not* do is decide what is on the page. Each journal is
    still asked for separately, over the endpoint that checks the
    permission belonging to it -- this only decides whether the page is
    worth opening at all.

    Args:
        permissions: Permission strings; holding any one of them passes.

    Usage::

        @require_any_permission("audit:view", "logs:view")
        def journals():
            ...
    """
    def decorator(view_func):
        @functools.wraps(view_func)
        def wrapper(*args, **kwargs):
            user = get_current_domain_user()
            authorization_service = g.get('authorization_service')

            if authorization_service is None:
                raise RuntimeError(
                    "AuthorizationService not found in g.authorization_service"
                )

            if any(
                authorization_service.is_allowed(user, permission)
                for permission in permissions
            ):
                return view_func(*args, **kwargs)

            if user is None:
                raise DomainError(
                    N_("Authentication required"), code="UNAUTHENTICATED"
                )
            raise PermissionDeniedError(
                N_("Not authorized"), required=list(permissions)
            )
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
                    N_("Authentication required"), code="UNAUTHENTICATED"
                )
            return redirect(url_for('frontend.login_page'))
        return view_func(*args, **kwargs)

    # Marked by the decorator below rather than by setting its attribute
    # here: the name `openapi.py` reads is written in one place, and the
    # reason it is read is written there too. This route needs a caller,
    # and this decorator is where that is true.
    return requires_credentials(wrapper)


def requires_credentials(view_func):
    """
    Mark a view that needs a caller but decides the rest for itself.

    ``require_permission`` says which permission opens a route, and the
    published document reads it to say whether a token is needed. Two
    kinds of route carry no such decorator and still cannot be used by
    anybody anonymous:

    * the journals, which pick the permission from the journal asked for
      -- ``audit:view`` for one, ``logs:view`` for the other, and the
      route's own docstring explains why the check cannot be a decorator;
    * ``change-password``, whose authorization *is* that the account is
      the one the request authenticated as.

    Without this mark the document said those operations needed no
    credentials while listing ``401`` among their answers. It carries no
    behaviour: the checks stay where they are, and this is only what lets
    the document describe them truthfully.

    Args:
        view_func: The view to mark.

    Returns:
        The same view.
    """
    cast(Any, view_func).requires_credentials = True
    return view_func
