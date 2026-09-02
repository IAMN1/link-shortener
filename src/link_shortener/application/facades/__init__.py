"""
What the web layer holds instead of the use cases themselves.

A facade here is one object per area of the service, and a method on one is
ordinarily a single line: take the call, hand it to the use case that does
it. What belongs here is an object that owns nothing, opens no transaction
and decides as little as possible; anything that owns state or opens a
transaction is a use case or a service, and goes where those go.

One method breaks the single line and is worth naming rather than
pretending away: ``AdminService.resend_verification`` reads the account
first, because the route needs the address the message went to and the use
case is deliberately given an address rather than an id -- the public
route reaches the same use case with a string a stranger typed.

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
