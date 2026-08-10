from typing import List

from pydantic import BaseModel, Field


class UserResponse(BaseModel):
    """The account, as every auth answer describes it."""

    id: str = Field(description="Account identifier.")
    email: str = Field(description="Address the account signs in with.")
    roles: List[str] = Field(description="Role names granted to it.")
    is_active: bool = Field(description="Whether it may sign in at all.")


class RegisterResponse(BaseModel):
    """Answer to a successful registration."""

    message: str = Field(description="Human-readable confirmation.")
    user: UserResponse = Field(description="The account that was created.")


class TokenPairResponse(BaseModel):
    """Answer to a successful sign-in.

    The tokens are in the body *and* in cookies: a browser client uses the
    cookies, an API client reads the body. Documented from the body, which
    is the part a generated client can see.
    """

    access_token: str = Field(description="Short-lived bearer token.")
    refresh_token: str = Field(description="Token that buys a new pair.")
    user: UserResponse = Field(description="The account that signed in.")


class RefreshResponse(BaseModel):
    """Answer to a successful refresh.

    No ``user``: the caller already knows who it is, and the refresh path
    reads the cookie rather than the account.
    """

    access_token: str = Field(description="The new bearer token.")
    refresh_token: str = Field(
        description="The new refresh token; the old one is spent."
    )


class MessageResponse(BaseModel):
    """An answer that carries nothing but a confirmation."""

    message: str = Field(description="Human-readable confirmation.")
