from flask import g
from link_shortener.application.ports.auth.authorization_service import AuthorizationService
from link_shortener.domain import DomainError, SystemPermissions


def check_can_view_link(owner_id: str | None, authorization_service: AuthorizationService) -> None:
    """
    Verify that the current user (from g) is allowed to view the link.

    Raises:
        DomainError: If the user is not authorized (code=FORBIDDEN).
    """
    user = g.get('_domain_user')
    if not user:
        raise DomainError("Authentication required", code="FORBIDDEN")

    # Admins and users with stats:view_any permission are always allowed.
    if authorization_service.is_allowed(user, SystemPermissions.ADMIN_ALL.value) or \
       authorization_service.is_allowed(user, SystemPermissions.STATS_VIEW_ANY.value):
        return

    # The link owner is always allowed.
    if owner_id is not None and owner_id == user.id:
        return

    raise DomainError("You are not allowed to view this link", code="FORBIDDEN")
