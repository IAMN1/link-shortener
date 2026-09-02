"""
Values that are what they hold, and that refuse to exist wrong.

A thing belongs here when it has no identity: two ``Email`` objects with
the same address are the same address, and there is no row to come back
to. They are frozen, and the ones with a shape to get wrong refuse it in
the constructor rather than leaving the caller to check -- ``OwnerID``
with no value and a hash that is not 64 hexadecimal characters cannot be
built at all, so everything downstream may stop asking.

Two members are modules of functions rather than classes:
``verification_token`` mints a mailed token and reduces it to what may
be stored, ``visitor`` reduces an address and a User-Agent to what a
chart may keep. They are here for the same reason the classes are --
what they are about is a value, with no identity anywhere in it.
"""
