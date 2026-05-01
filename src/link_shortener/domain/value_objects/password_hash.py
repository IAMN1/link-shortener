from dataclasses import dataclass


@dataclass(frozen=True)
class PasswordHash:
    """
    Value object that holds a hashed password.

    The domain does not know which hashing algorithm was used; that detail
    belongs to the infrastructure layer. The value is an opaque string.

    Attributes:
        value: The hashed password string (e.g., bcrypt or argon2 output).
    """
    value: str

    def __str__(self) -> str:
        """Return the PasswordHash as string."""
        return self.value
