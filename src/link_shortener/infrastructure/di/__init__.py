"""
Which implementation a deployment gets, decided once.

What goes in is assembly: reading the profile, choosing between a component
and its fallback, and holding the objects that must exist once per process.
Nothing here does any of the service's work -- every object built here would
behave the same if a test constructed it by hand, which is the point.
"""
