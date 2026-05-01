from dataclasses import dataclass

from link_shortener.application.dtos.user import UserResponse


@dataclass
class LoginResponse:
    """
    DTO returned after successful login.

    Attributes:
        access_token: JWT access token.
        refresh_token: JWT refresh token.
        user: User data.
    """
    access_token: str
    refresh_token: str
    user: UserResponse


@dataclass
class RegisterResponse:
    """
    DTO returned after successful registration.

    Attributes:
        user: Newly created user data.
        message: Success message.
    """
    user: UserResponse
    message: str = "User registered successfully"
