"""
What the application needs from outside itself, stated as an interface.

A port goes here when the application layer must name a capability it does
not implement -- storage, a cache, a clock on somebody else's machine, a
mail transport, a queue -- so that a use case can depend on the name and
the infrastructure can supply the thing. The interface is declared here and
implemented in ``infrastructure``; nothing in this directory imports from
there.

The value types a port's own methods take and return live with that port
rather than in ``dtos``: they are part of the interface being declared, and
splitting them from it would mean reading two files to learn one contract.
"""
