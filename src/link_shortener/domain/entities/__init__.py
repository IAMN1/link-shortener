"""
What the service can name, come back to, and find changed.

A thing belongs here when it has an identity the service keeps: an id it
can be looked up by, so that two of them with identical fields are still
two things. That is the line against ``value_objects`` next door, where
two with identical fields are one value. It is also why ``Link`` and
``User`` compare on their id and on nothing else -- a link whose click
counter has moved is the same link.

A rule about one such thing is written on it -- ``User.has_permission``,
``Role.ensure_may_be_changed`` -- while a rule about no single one of
them belongs in ``policies``.

The read shapes a repository returns about an entity -- ``VisitSummary``
and its parts -- sit in that entity's own module rather than in a
directory of their own. They are answers to a question about it, and
they have no identity to keep.
"""
