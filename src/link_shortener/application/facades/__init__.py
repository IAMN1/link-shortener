"""
What the web layer holds instead of the use cases themselves.

A facade here is one object per area of the service, and every method on one
is a single line: take the call, hand it to the use case that does it. What
belongs here is an object that owns nothing, decides nothing and opens no
transaction; anything that does one of those is a use case or a service, and
goes where those go.

That rule is what separates this directory from ``application/services``. A
service there is called *by* a use case and takes the unit of work the use
case opened, so it sits in the middle of somebody else's transaction. A
facade is called from above and opens nothing. Both were once called
services, in one directory, with only the first argument to tell them apart.

The alternative to a facade is a web controller that lists the use cases it
needs, which grows a constructor argument with every use case added to its
area and makes the container wire them per controller rather than per area.
"""

from .admin_service import AdminService
from .auth_service import AuthService
from .link_service import LinkService

__all__ = ["AdminService", "AuthService", "LinkService"]
