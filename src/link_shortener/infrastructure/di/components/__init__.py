"""
One family of dependencies each, built when first asked for.

What goes in is a component that owns the construction of related objects
and the choice between their implementations -- the cache and its fallback,
the queue and its null form, the mailer and the profile that decides whether
anything is sent. Split by family rather than by layer, so that adding a
dependency touches one file instead of the container.
"""
