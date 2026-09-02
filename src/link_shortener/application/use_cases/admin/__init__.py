"""
Acts an operator takes on the service, or on somebody else's account.

The line against ``use_cases/auth`` next door is who the act is about: there
an account acts on itself, here somebody acts on another account or on the
service as a whole. Every act here is behind a permission, and each names
one of its own.

``privilege_guard.py`` is not an act. It is the part of the privilege rules
that needs a unit of work -- reading the actor and counting administrators
inside the transaction the act runs in -- and it sits here because that is
the only place those rules are applied.
"""
