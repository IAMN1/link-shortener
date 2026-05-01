from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from link_shortener.domain import User


@dataclass
class UserResponse:
    """
    User data sent in API responses.

    Attributes:
        id: Unique user ID.
        email: User's email.
        roles: List of role names assigned.
        is_active: Account status.
        created_at: Registration timestamp.
        last_login: Last login timestamp (if any).
    """
    id: str
    email: str
    roles: List[str]
    is_active: bool
    created_at: datetime
    last_login: Optional[datetime] = None

    @classmethod
    def from_user(cls, user: User) -> "UserResponse":
        """
        Convert a domain User entity to a DTO.

        Args:
            user: Domain User.

        Returns:
            UserResponse.
        """
        return cls(
            id=user.id,
            email=user.email.value,
            roles=[role.name for role in user.roles],
            is_active=user.is_active,
            created_at=user.created_at,
            last_login=user.last_login,
        )
