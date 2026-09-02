from typing import List

from pydantic import BaseModel, Field

from link_shortener.application.dtos.user import (
    UserResponse as UserResponseDto,
)


class UserResponse(BaseModel):
    """The account, as every auth answer describes it.

    Four fields where ``admin.UserResponseSchema`` carries seven, and the
    three left out are the difference between describing an account to
    itself and describing it to an operator. ``created_at`` and
    ``last_login`` are an account's history, which the sign-in answer has
    no use for; ``email_verified`` is a question that cannot be open here,
    because an unconfirmed address is refused at the sign-in and never
    reaches this shape.
    """

    id: str = Field(description="Account identifier.")
    email: str = Field(description="Address the account signs in with.")
    roles: List[str] = Field(description="Role names granted to it.")
    is_active: bool = Field(description="Whether it may sign in at all.")

    @classmethod
    def from_dto(cls, dto: UserResponseDto) -> "UserResponse":
        """
        Narrow the application's view of an account to this one.

        Named rather than spelled out at the call site, for the reason
        every other schema here has a ``from_dto``: a controller writing
        the dictionary itself is a second copy of the field list, and the
        day the DTO gains a field is the day the two disagree about
        whether it is published.

        Args:
            dto: The account as the application layer describes it.

        Returns:
            The account as an auth answer describes it.
        """
        return cls(
            id=dto.id,
            email=dto.email,
            roles=dto.roles,
            is_active=dto.is_active,
        )


class RegisterResponse(BaseModel):
    """Answer to a registration attempt.

    Carries a sentence and nothing else. Carrying the account as well
    would mean the answer could only be given when there is an account to
    describe -- and the absence of one would itself say that an address is
    taken. Both outcomes produce this.
    """

    message: str = Field(description="Human-readable acknowledgement.")


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
