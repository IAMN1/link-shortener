"""
Per-object authorization helpers for the web layer.

Permissions answer "may this role do this kind of thing"; these helpers
answer "may this caller do it to *this* link". Both questions have to be
asked, which is why the decorators in ``decorators.py`` are not enough on
their own.
"""

from flask import g

from link_shortener.application.ports.auth.authorization_service import AuthorizationService
from link_shortener.domain import DomainError, SystemPermissions


def can_view_link_details(
    owner_id: str | None,
    authorization_service: AuthorizationService,
) -> bool:
    """
    Report whether the current caller may see a link's private details.

    Private details are the owner's identifier and the analytics derived
    from the link's traffic. Both were public for any code until now: the
    basic endpoint handed out the owner's UUID, and the extended one handed
    out their traffic, to anyone who could guess a six-character code.

    Args:
        owner_id: Identifier of the link's owner, or ``None`` for a link
            created by a guest.
        authorization_service: Service that answers permission questions.

    Returns:
        ``True`` if the caller owns the link, is an admin, or holds
        ``stats:view_any``.
    """
    user = g.get('_domain_user')
    if not user:
        return False

    # Admins and users with stats:view_any are always allowed.
    if authorization_service.is_allowed(user, SystemPermissions.ADMIN_ALL.value) or \
       authorization_service.is_allowed(user, SystemPermissions.STATS_VIEW_ANY.value):
        return True

    # The link owner is always allowed. A guest link has no owner, so it is
    # nobody's to claim -- ``None == None`` must not read as ownership.
    return owner_id is not None and owner_id == user.id


def require_can_view_link_details(
    owner_id: str | None,
    authorization_service: AuthorizationService,
) -> None:
    """
    Verify that the current caller may see a link's private details.

    Args:
        owner_id: Identifier of the link's owner, or ``None`` for a link
            created by a guest.
        authorization_service: Service that answers permission questions.

    Raises:
        DomainError: With code ``UNAUTHENTICATED`` when nobody is logged in
            and ``FORBIDDEN`` when the caller is logged in but not entitled.
            The two are kept apart so a client can tell "log in" from
            "logging in will not help".
    """
    if not g.get('_domain_user'):
        raise DomainError("Authentication required", code="UNAUTHENTICATED")

    if not can_view_link_details(owner_id, authorization_service):
        raise DomainError("You are not allowed to view this link", code="FORBIDDEN")
