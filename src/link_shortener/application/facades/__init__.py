"""
What the web layer holds instead of thirty use cases.

A facade here is one object per area -- links, administration -- whose every
method is one line: take the call, hand it to the use case that does it.
That is the whole of what they are for, and the reason they are not in
``application/services`` beside ``UserManagementService`` and
``RoleManagementService``: those are called *by* use cases and take the unit
of work the caller opened, so the two kinds of object sit on opposite sides
of the same layer and only the signature said so.

The alternative is a controller that lists the use cases it needs, and it
was worse in the two places it showed: ``ApiController`` would name eight
constructor arguments where it now names one, and ``AuthController`` did
name eight -- the rule was written here and applied to one of the areas it
was written for. The container would also wire them per controller rather
than per area.
"""

from .admin_service import AdminService
from .auth_service import AuthService
from .link_service import LinkService

__all__ = ["AdminService", "AuthService", "LinkService"]
