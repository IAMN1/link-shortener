"""
What turns a configured type into a chain that writes.

A manager here reads the type a deployment asked for, builds the
implementations in the order that type implies, and puts a failover service
in front of them when there is more than one. It then answers for the chain
it built: which implementation is doing the work, what has been lost, and
what the last background check found.

Kept per port rather than merged, because the chains fail apart: the
journal can be unwritable while the audit trail is fine, and a deployment
can switch either off without touching the other.
"""
