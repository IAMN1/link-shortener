"""
One file per role a cache plays for this service.

A role is a set of operations that answer one question -- what a link is,
where a code redirects to, what the service's totals are, whether the
backend is there, what an operator may do to it. They are declared apart
because a use case that needs one has no business holding the others.

``ServiceCache`` is the exception and the reason the rest are split: it
declares nothing of its own and names the combination, for the places that
hold the object rather than one of its roles.
"""
