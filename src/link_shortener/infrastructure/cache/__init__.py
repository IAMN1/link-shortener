"""
Somewhere to put an answer that cost something to get.

What goes in is an implementation of the roles ``ServiceCache`` names, and
whatever such an implementation needs to hold a value safely across a
process boundary -- which is why ``signing.py`` is here rather than beside
the entities it protects.

The rule every member keeps: nothing here may be the only copy of anything.
A cache that has forgotten everything, or that was never configured at all,
costs time and must never cost correctness.
"""
