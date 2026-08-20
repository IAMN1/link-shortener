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


# There is deliberately no ``RegisterResponse`` here. One stood in this
# file carrying ``user`` and "User registered successfully", and nothing
# ever built it -- which was just as well, because it described the
# opposite of what registration does. ``RegisterUseCase`` returns nothing
# on purpose: the answer is the same whether the address was free or
# already taken, and an account handed back would say which. A DTO that
# says otherwise is a standing invitation to wire it up, and it shares its
# name with ``web.schemas.auth.RegisterResponse``, which carries a
# sentence and nothing else and is what the endpoint actually answers.
