from flask import g, request
from link_shortener.application import RequestContext


def get_client_ip() -> str:
    """
    Extract the real client IP address from the request, accounting for proxies.

    Returns:
        Client IP as string, or empty string if not available.
    """
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    return request.remote_addr or ''

def create_request_context() -> RequestContext:
    """
    Create a RequestContext object from the current Flask request.

    The request ID is taken from Flask's `g` object, which is set by
    the RequestLoggingMiddleware.

    Returns:
        RequestContext populated with request metadata.
    """
    return RequestContext(
        request_id=getattr(g, 'request_id', None),
        remote_addr=get_client_ip(),
        user_agent=request.headers.get('User-Agent'),
        request_path=request.path,
        request_method=request.method,
    )