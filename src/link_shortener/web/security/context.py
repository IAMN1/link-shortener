"""
Request context helpers.

Functions to extract client information from Flask request and build
a ``RequestContext`` as well as load the full domain ``User`` for the
current request.
"""

from typing import Optional
from flask import current_app, g, request

from link_shortener.application import RequestContext
from link_shortener.domain import User


def get_client_ip() -> str:
    """
    Extract the real client IP address, accounting for proxies.

    If the ``X-Forwarded-For`` header is present, the first IP in the list
    is returned. Otherwise ``request.remote_addr`` is used.

    Returns:
        Client IP string, or an empty string if unavailable.
    """
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    return request.remote_addr or ''


def create_request_context() -> RequestContext:
    """
    Build a ``RequestContext`` from the current Flask request.

    The ``request_id`` is taken from ``g.request_id``, which is set by
    the ``RequestLoggingMiddleware``. The ``current_user`` is taken from
    ``g.current_user``, set by ``AuthenticationMiddleware``.

    Returns:
        Populated ``RequestContext`` object.
    """
    return RequestContext(
        request_id=getattr(g, 'request_id', None),
        remote_addr=get_client_ip(),
        user_agent=request.headers.get('User-Agent'),
        request_path=request.path,
        request_method=request.method,
        current_user=getattr(g, "current_user", None)
    )


def get_current_domain_user() -> Optional[User]:
    """
    Load the full domain User entity for the current request.

    Uses ``g.current_user`` (set by AuthenticationMiddleware) and loads the
    corresponding User from the database in a read-only Unit of Work.
    The result is cached in ``g._domain_user`` for the duration of the request.

    Returns:
        Domain ``User`` instance or ``None`` if no user is authenticated.
    """
    if not hasattr(g, "current_user") or g.current_user is None:
        return None

    # Return cached domain user if already loaded
    if hasattr(g, "_domain_user"):
        return g._domain_user

    container = current_app.container
    uow_factory = container.get_uow_factory()
    with uow_factory(read_only=True) as uow:
        user = uow.users.find_by_id(g.current_user.id)
        g._domain_user = user
        return user
