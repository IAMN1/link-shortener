from dataclasses import dataclass


@dataclass(frozen=True)
class PasswordHash:
    """
    Value object that holds a hashed password.

    The domain does not know which hashing algorithm was used; that detail
    belongs to the infrastructure layer. The value is an opaque string.

    Opaque is not the same as unchecked. What this object promises its
    readers is that something stands between a password and the column,
    and an empty value is the one shape that breaks the promise outright:
    ``bcrypt.checkpw`` refuses it, so an account carrying one cannot be
    signed into at all -- by its owner or by anybody -- and the failure
    surfaces as a wrong password rather than as the broken row it is. It
    is reachable from both directions: a hashing service that returned
    ``""`` on some path, and a row read back from a database where the
    column was cleared by hand or by a migration that never filled it.

    Nothing stronger is checked here, and that is the line this object
    draws. A rule about ``$2b$`` prefixes or a length would be a rule
    about bcrypt, which is precisely what the domain is not supposed to
    know: the algorithm is swappable by design, and a check that outlives
    the swap is a check that refuses correct data.

    Attributes:
        value: The hashed password string (e.g., bcrypt or argon2 output).
    """
    value: str

    def __post_init__(self):
        """
        Refuse a hash that hashes nothing.

        Raises:
            ValueError: If the value is empty or only whitespace.
        """
        # ``ValueError`` rather than the ``ValidationError`` its neighbour
        # ``Email`` raises, and the difference is who is at fault. An
        # address is typed by somebody, so a malformed one is their
        # request and is answered 400. Nobody types a hash: an empty one
        # is this service's own state gone wrong, either in the code that
        # produced it or in the row it was read back from. The web layer
        # deliberately has no handler for ``ValueError`` for exactly this
        # case -- it falls through to the 500 handler, which logs the
        # traceback an operator needs and tells the caller nothing.
        if not self.value or not self.value.strip():
            raise ValueError("Password hash must not be empty")

    def __str__(self) -> str:
        """Return the PasswordHash as string."""
        return self.value
