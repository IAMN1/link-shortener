"""
What the pages are allowed to offer, answered by the authorization service.

The markup used to decide what to show by reading role names off the
current user: ``{% if 'analyst' in g.current_user.roles %}``. The server
decides by permission, so the two answered different questions and drifted
apart wherever a role held a permission its name did not imply -- an
analyst was offered "Create Link" it may not use, and a plain user was
never offered the service statistics it may read. A role invented through
the admin panel was invisible to the markup entirely, since its name is in
no template.

``can`` asks the same service ``require_permission`` asks, so a page can
only offer what the request behind it would be allowed to do.
"""

from flask import Flask, g

from link_shortener.web.security.context import get_current_domain_user


def can(permission: str) -> bool:
    """
    Report whether this request's caller holds a permission.

    Answers for anonymous callers too: they act under the ``guest`` role,
    which is how the landing page knows whether to offer its forms.

    Results are memoised per request. The anonymous branch of the service
    opens a Unit of Work to read the guest role, and a sidebar asks about
    seven permissions -- without this, drawing the menu for a signed-out
    visitor would be seven round trips to the database.

    Args:
        permission: Permission string, e.g. ``"link:create"``.

    Returns:
        ``True`` when the caller may do it.
    """
    cache = g.setdefault("_template_permissions", {})
    if permission not in cache:
        service = g.get("authorization_service")
        if service is None:
            # No middleware ran, so nothing established who is calling.
            # Offering nothing is the safe answer; the request would be
            # refused anyway.
            return False
        cache[permission] = service.is_allowed(get_current_domain_user(), permission)
    return cache[permission]


def register_template_access(app: Flask) -> None:
    """
    Make ``can`` available to every template.

    Args:
        app: The application to register the context processor on.
    """
    @app.context_processor
    def inject_access():  # pragma: no cover - trivial closure, exercised via templates
        return {"can": can}
