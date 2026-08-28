"""
The two questions about a caller that the application cannot answer itself.

Who they are -- credentials, sessions, tokens -- and what they may do. Both
need machinery the application layer does not own: a hashing algorithm and
a token library for the first, the stored roles and permissions for the
second. A port goes here when it answers one of those two and nothing else.
"""
