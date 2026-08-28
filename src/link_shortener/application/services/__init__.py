"""
The work several use cases do the same way.

A service here is called *by* a use case and takes that use case's unit of
work: it is the middle of a transaction somebody else opened and will
commit. What earns a place here is being reached from more than one use
case: work only one of them does belongs inside that use case rather than in
a directory of its own.

The facades the web layer holds are the other kind of object and live in
``application/facades``: they are called from above, open nothing, and
delegate. Both were once called services, in one directory, with only the
first argument to tell them apart.
"""
