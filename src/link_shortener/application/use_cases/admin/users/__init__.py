"""
Acts an operator takes on an account that is not their own.

Creating one, removing one, switching it on or off, confirming its address
on their word, changing which roles it wears. Each is behind
``admin:manage_users`` or ``admin:view_users``, and each leaves a record
naming the operator and the account separately.

``clean_unverified_accounts.py`` is the member with no operator behind it:
the schedule removes registrations nobody confirmed. It belongs by the same
rule read at the outcome instead of the actor -- an account ceases to exist.
"""
