"""
Everything on the path by which an account proves who it is.

Signing in, registering, confirming an address, changing a password and
resetting a forgotten one -- acts an account takes on itself, which is the
line against ``use_cases/admin``, where somebody acts on another account.

The ``send_*_email`` modules are here because they are the other half of
those acts, not separate ones: a confirmation, a reset link and the
notice sent to an address somebody tried to register again. Each is its own
module because both the background worker and the synchronous fallback run
it, and a message assembled in two places is two messages.
"""
