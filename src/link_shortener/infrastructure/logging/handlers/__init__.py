"""
The implementations the logging ports are satisfied by.

What goes in is a class that answers ``Logger`` or ``AuditLogger`` and
knows exactly one way of writing -- through structlog, through the standard
library, or by discarding. They know nothing of each other, which is what
lets one stand in for another when the one in use stops writing.

``raising.py`` is not one of them: it holds standard-library handlers, not
port implementations. It sits here because what it changes is the same
thing these are chosen between for -- whether a write that failed is
noticed by anybody.
"""
