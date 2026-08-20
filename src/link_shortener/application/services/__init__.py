"""
The work several use cases do the same way.

A service here is called *by* a use case and takes that use case's unit of
work: it is the middle of a transaction somebody else opened and will
commit. ``UserManagementService`` is reached from nine use cases and
``RoleManagementService`` from three, which is what earns them a place of
their own rather than a home inside whichever use case happened to need
them first.

The facades the web layer holds are the other kind of object and live in
``application/facades``: they are called from above, open nothing, and
delegate. Both were once called services, in one directory, with only the
first argument to tell them apart.
"""
