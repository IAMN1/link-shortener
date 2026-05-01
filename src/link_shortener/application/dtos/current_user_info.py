from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class CurrentUserInfo:
    """
    Immutable snapshot of the current authenticated user for request context.

    Attributes:
        id: User's unique identifier.
        email: User's email.
        roles: List of role names assigned.
        is_active: Flag indicating account status.
    """
    id: str
    email: str
    roles: List[str]
    is_active: bool
