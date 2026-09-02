"""
Per-object authorization helpers for the web layer.

Permissions answer "may this role do this kind of thing"; these helpers
answer "may this caller do it to *this* link". Both questions have to be
asked, which is why the decorators in ``decorators.py`` are not enough on
their own.
"""

from typing import Optional

from flask import current_app, g, request

from link_shortener.application.ports.auth.authorization_service import AuthorizationService
from link_shortener.domain import DomainError, PermissionDeniedError, SystemPermissions
from link_shortener.domain.i18n import N_
from link_shortener.web.security.deletion_token import link_id_from


DELETION_TOKEN_HEADER = "X-Deletion-Token"  # nosec B105
"""The header a creator returns their proof in.

Named once. Three routes read it, and a name spelled at each of them is a
name that gets changed at two of them.

The `nosec` is what this repository does with a finding that has been
read, as the `AuditEvent` members spelled this way already are: bandit's
B105 matches the *name* of a binding rather than its contents, so anything
called `..._TOKEN` is reported as a hardcoded password. What this one holds
is the name of a header; the value that travels in it is minted per link in
`deletion_token.py` and is written down nowhere. Unannotated it took the
whole lint gate with it, because bandit exits non-zero on any finding at
all -- so an examined one has to be marked rather than merely known about.
"""


def can_view_link_details(
    owner_id: str | None,
    authorization_service: AuthorizationService,
) -> bool:
    """
    Report whether the current caller may see a link's private details.

    Private details are the owner's identifier and the analytics derived
    from the link's traffic. Both were public for any code until now: the
    basic endpoint handed out the owner's UUID, and the extended one handed
    out their traffic, to anyone who could guess a seven-character code.

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
        raise DomainError(N_("Authentication required"), code="UNAUTHENTICATED")

    if not can_view_link_details(owner_id, authorization_service):
        raise PermissionDeniedError(N_("You are not allowed to view this link"))


def presented_link_id() -> Optional[str]:
    """
    The link a caller's deletion token names, if they presented one.

    The single door onto the header, and it does one thing besides read
    it: it records on ``g`` that this request's answer depends on the
    header. ``PrivateCacheMiddleware`` reads that mark and adds ``Vary``,
    which is the part that kept getting forgotten -- the basic link
    endpoint carried it, its ``/extended`` neighbour read the same header,
    answered two different bodies from it and said nothing, so a shared
    cache was free to store the fuller answer and hand it to a caller with
    no token.

    Returns:
        The identifier the token names, or ``None`` when the header is
        absent, forged, or signed with another key.
    """
    g.deletion_token_was_read = True
    return link_id_from(
        current_app.config["SECRET_KEY"],
        request.headers.get(DELETION_TOKEN_HEADER),
    )


def made_this_link(link_id: Optional[str]) -> bool:
    """
    Whether the caller proved they created this particular link.

    The identifier is compared, not the short code: codes are freed by
    deletion and issued again, so a token naming one would go on proving
    something about whatever link took it next.

    A match means the answer about to be built carries figures that belong
    to one caller, so this marks the request for ``no-store`` as well --
    ``Vary`` alone leans on every cache in the path implementing it
    correctly.

    Args:
        link_id: Identifier of the link being answered about, or ``None``
            when the row carries none.

    Returns:
        ``True`` when the presented token names exactly this link.
    """
    matched = link_id is not None and link_id == presented_link_id()
    if matched:
        g.deletion_token_matched = True
    return matched
