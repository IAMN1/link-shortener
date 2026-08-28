"""
Building the acts an operator takes on the service, or on another account.

What goes in follows the grouping of the acts themselves -- links, roles,
accounts -- because each group needs a different set of ports, and one
component holding all of them would build the whole container to answer any
single request.
"""
