"""
Building the acts an account takes on itself.

Signing in, registering, confirming an address, replacing a password and the
messages each of those sends are wired together because they share the same
ports: the account store, the token service, the mailer and the queue that
carries a message out of the request.
"""
