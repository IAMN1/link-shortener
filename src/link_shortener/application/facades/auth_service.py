from dataclasses import dataclass
from typing import Optional

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.auth import LoginResponse, RefreshedTokens
from link_shortener.application.ports.auth.auth_service import (
    AuthenticationService,
)
from link_shortener.application.use_cases.auth.change_password import (
    ChangePasswordUseCase,
)
from link_shortener.application.use_cases.auth.login import LoginUseCase
from link_shortener.application.use_cases.auth.register import RegisterUseCase
from link_shortener.application.use_cases.auth.request_password_reset import (
    RequestPasswordResetUseCase,
)
from link_shortener.application.use_cases.auth.resend_verification import (
    ResendVerificationUseCase,
)
from link_shortener.application.use_cases.auth.reset_password import (
    ResetPasswordUseCase,
)
from link_shortener.application.use_cases.auth.verify_email import (
    VerifyEmailUseCase,
)


@dataclass
class AuthService:
    """
    Application facade for everything an account does with itself.

    Signing in and out, registering, confirming an address, refreshing a
    session, changing a password and resetting a forgotten one. The
    counterpart is ``AdminService``, which is what an operator does to
    *other* people's accounts; the line between them is who the act is
    about.

    Not to be confused with ``application.ports.auth.AuthenticationService``,
    which this holds. That one is a port -- an interface the
    infrastructure implements, minting and retiring tokens. This one is a
    facade: it owns nothing and decides nothing, and every method below is
    one line handing the call to whatever does it.

    Why it exists, in the words the directory already uses: "The
    alternative is a controller that lists the use cases it needs, and it
    was worse in the one place it shows: ``ApiController`` would name
    eight constructor arguments where it now names one." ``AuthController``
    was the second such place and named eight -- the rule was written down
    and applied to one of the two areas it was written for.

    Attributes:
        authentication_service: The port. Reached directly for signing out
            and for refreshing, which are token operations with no use
            case of their own: there is no policy in either beyond
            retiring a session and issuing a pair.
        login_use_case: Checks credentials and opens a session.
        register_use_case: Creates an account and mails its confirmation.
        verify_email_use_case: Spends a confirmation token.
        resend_verification_use_case: Issues a fresh confirmation.
        change_password_use_case: Replaces the caller's own password.
        request_password_reset_use_case: Mails a reset link.
        reset_password_use_case: Spends a reset token.
    """

    authentication_service: AuthenticationService
    login_use_case: LoginUseCase
    register_use_case: RegisterUseCase
    verify_email_use_case: VerifyEmailUseCase
    resend_verification_use_case: ResendVerificationUseCase
    change_password_use_case: ChangePasswordUseCase
    request_password_reset_use_case: RequestPasswordResetUseCase
    reset_password_use_case: ResetPasswordUseCase

    # ------------------------------------------------------------------
    # Signing in and out
    # ------------------------------------------------------------------
    def login(
        self, email: str, password: str, context: RequestContext
    ) -> LoginResponse:
        """Authenticate an account and open a session for it.

        Args:
            email: Registered address.
            password: Plain-text password.
            context: Request context.

        Returns:
            The tokens of the new session and the account they belong to.
        """
        return self.login_use_case.execute(email, password, context)

    def logout(self, refresh_token: str) -> bool:
        """End the session a refresh token belongs to.

        Args:
            refresh_token: The token naming the session.

        Returns:
            True if a live session was found and revoked.
        """
        return self.authentication_service.revoke_refresh_token(refresh_token)

    def logout_session(self, chain_id: str) -> int:
        """End a session named by its chain, for a client holding no
        refresh token.

        Args:
            chain_id: The ``sid`` claim of the access token.

        Returns:
            Number of sessions revoked.
        """
        return self.authentication_service.revoke_session_chain(chain_id)

    def refresh(self, refresh_token: str) -> Optional[RefreshedTokens]:
        """Exchange a refresh token for a fresh pair, rotating it.

        Args:
            refresh_token: The token to spend.

        Returns:
            The new pair, or None if the token cannot be spent.
        """
        return self.authentication_service.refresh_access_token(refresh_token)

    # ------------------------------------------------------------------
    # Registering and confirming
    # ------------------------------------------------------------------
    def register(
        self, email: str, password: str, context: RequestContext
    ) -> None:
        """Register an address, or say nothing about one already taken.

        Args:
            email: Address to register.
            password: Plain-text password.
            context: Request context.
        """
        self.register_use_case.execute(email, password, context)

    def verify_email(self, token: str, context: RequestContext) -> None:
        """Confirm the address a token was mailed to.

        Args:
            token: The token from the confirmation link.
            context: Request context.
        """
        self.verify_email_use_case.execute(token, context)

    def resend_verification(self, email: str, context: RequestContext) -> None:
        """Send a fresh confirmation, if there is anything to confirm.

        The outcome is deliberately dropped: which of the three things
        happened is what the public route exists not to say.

        Args:
            email: Address to send to.
            context: Request context.
        """
        self.resend_verification_use_case.execute(email, context)

    # ------------------------------------------------------------------
    # Passwords
    # ------------------------------------------------------------------
    def change_password(
        self,
        user_id: str,
        current_password: str,
        new_password: str,
        context: RequestContext,
    ) -> RefreshedTokens:
        """Replace one account's password on the strength of the old one.

        Args:
            user_id: The account making the request, as authenticated.
            current_password: The password it is signed in with.
            new_password: What to replace it with.
            context: Request context.

        Returns:
            A fresh pair of tokens, opened after every earlier session was
            revoked.
        """
        return self.change_password_use_case.execute(
            user_id=user_id,
            current_password=current_password,
            new_password=new_password,
            context=context,
        )

    def request_password_reset(
        self, email: str, context: RequestContext
    ) -> None:
        """Mail a reset link, if there is anywhere to send one.

        The outcome is deliberately dropped, as with the resend above.

        Args:
            email: Address to send to.
            context: Request context.
        """
        self.request_password_reset_use_case.execute(email, context)

    def reset_password(
        self, token: str, new_password: str, context: RequestContext
    ) -> None:
        """Set a new password from a mailed token.

        Args:
            token: The token from the reset link.
            new_password: What to set the password to.
            context: Request context.
        """
        self.reset_password_use_case.execute(token, new_password, context)
