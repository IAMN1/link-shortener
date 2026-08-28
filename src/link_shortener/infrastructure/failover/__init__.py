"""
Carrying on when a component stops answering.

What goes in is the mechanism that holds several implementations of one port
and moves the work to the next when the one in use fails -- and moves it
back when that one recovers. It knows nothing about what is being written or
read through it.

``minimal_logger.py`` is here because this mechanism runs before the logging
it protects exists, and it must be able to say what it did.
"""
