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
class RefreshedTokens:
    """
    DTO returned after a refresh token is exchanged.

    Both tokens are replaced: the refresh token is rotated so the one just
    spent cannot be used again.

    Attributes:
        access_token: Newly issued JWT access token.
        refresh_token: Newly issued JWT refresh token.
    """
    access_token: str
    refresh_token: str


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
