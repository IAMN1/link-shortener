"""
Request helper utilities.

Functions for extracting the client IP and building a ``RequestContext``
from the current Flask request.
"""

from flask import g, request
from link_shortener.application import RequestContext


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
