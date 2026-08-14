"""
Request context helpers.

Functions to extract client information from Flask request and build
a ``RequestContext`` as well as load the full domain ``User`` for the
current request.
"""

import ipaddress
from typing import Optional
from flask import current_app, g, request

from link_shortener.application import RequestContext
from link_shortener.domain import User


def get_client_ip() -> str:
    """
    Extract the real client IP address, accounting for trusted proxies.

    Only trusts X-Forwarded-For when the request comes from a trusted proxy,
    and then reads the **last** entry, not the first.

    A proxy appends; it does not prepend. Nginx's
    ``$proxy_add_x_forwarded_for`` writes whatever the client sent and then
    the address it actually saw, so the rightmost entry is the only one the
    client could not choose and every entry to its left is a string the
    client typed. Reading the leftmost handed the caller their own identity
    to declare: a fresh value per request made the guest quota count
    nothing, and a victim's address made the attacker's links come out of
    the victim's allowance and lock them out for the day.

    The value is also required to be an address, and returned in its
    canonical form. It becomes ``urls.guest_identifier``, a
    ``VARCHAR(45)``: a long header would fail the insert on PostgreSQL,
    and two spellings of one IPv6 address would count as two guests.

    Returns:
        Client IP string, or an empty string if unavailable.
    """
    trusted_proxies = current_app.config.get("TRUSTED_PROXIES", [])
    remote_addr = request.remote_addr or ''

    if remote_addr in trusted_proxies:
        forwarded_for = request.headers.get('X-Forwarded-For')
        if forwarded_for:
            nearest = _as_ip_address(forwarded_for.rsplit(',', 1)[-1])
            if nearest:
                return nearest

    return remote_addr


def _as_ip_address(value: str) -> Optional[str]:
    """
    Return the canonical form of an IP address, or ``None``.

    Args:
        value: One entry of an ``X-Forwarded-For`` header.

    Returns:
        The address in canonical form, or ``None`` if the entry is not a
        bare IP address -- in which case the header is not usable and the
        connection's own address is the truthful answer.
    """
    candidate = value.strip()
    if candidate.startswith("[") and candidate.endswith("]"):
        candidate = candidate[1:-1]  # Some proxies bracket IPv6 addresses

    if "%" in candidate:
        # A scope identifier names an interface on the machine reading it,
        # so it says nothing about a caller two hops away -- and Python
        # accepts any text after "%". That made the identity both forgeable
        # and unbounded: ``fe80::1%eth0``, ``%eth1``, ``%eth2`` are one
        # address and three guests, which empties the guest quota, and a
        # long enough tail overran ``guest_identifier`` (VARCHAR(45)) and
        # failed the insert on PostgreSQL.
        return None

    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


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

    The entity is cached in ``g._domain_user`` by
    ``AuthenticationMiddleware``; this function only reads it.
    """
    return getattr(g, '_domain_user', None)
