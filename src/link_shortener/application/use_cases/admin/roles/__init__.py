"""
Acts that change what a role grants, or whether it exists.

The widest-reaching acts the service allows: a change here moves every
account wearing the role at once, without any of them being touched. That
is why each records both sides of what it changed and how many accounts it
reached.

Acts that change which roles an account wears are next door in ``users``:
the line is whether the role or the account is what changed.
"""
