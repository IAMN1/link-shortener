"""
One HTTP route each, and nothing behind it.

What goes in is a class that reads a request, calls one use case, and turns
the answer into a response. The work is the use case's -- a controller that
would be hard to test without HTTP is a controller holding something that
belongs a layer down.

Split by audience rather than by entity: what the API answers, what the
panel renders, what an operator alone may reach.
"""
