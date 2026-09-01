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
from link_shortener.application.use_cases.auth.refresh_session import (
    RefreshSessionUseCase,
)
from link_shortener.application.use_cases.auth.reset_password import (
    ResetPasswordUseCase,
)
from link_shortener.application.use_cases.auth.sign_out import SignOutUseCase
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

    Why it exists is the rule stated in the directory's own docstring: a
    controller that lists the use cases it needs names an argument apiece
    and grows another with every use case added to its area. Holding this
    instead, ``AuthController`` names one argument whatever the area
    gains.

    Attributes:
        authentication_service: The port, held for the callers that ask
            this facade to validate a token. Signing out and refreshing
            went through it directly while neither had a use case; both
            have one now, because recording what happened is policy and
            the journal was empty for both.
        login_use_case: Checks credentials and opens a session.
        register_use_case: Creates an account and mails its confirmation.
        verify_email_use_case: Spends a confirmation token.
        resend_verification_use_case: Issues a fresh confirmation.
        change_password_use_case: Replaces the caller's own password.
        request_password_reset_use_case: Mails a reset link.
        reset_password_use_case: Spends a reset token.
        sign_out_use_case: Retires one session and records it.
        refresh_session_use_case: Rotates a refresh token, and records a
            replay of one.
    """

    authentication_service: AuthenticationService
    login_use_case: LoginUseCase
    register_use_case: RegisterUseCase
    verify_email_use_case: VerifyEmailUseCase
    resend_verification_use_case: ResendVerificationUseCase
    change_password_use_case: ChangePasswordUseCase
    sign_out_use_case: SignOutUseCase
    refresh_session_use_case: RefreshSessionUseCase
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

    def sign_out(
        self,
        context: RequestContext,
        refresh_token: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> bool:
        """End one session, by whichever token the client holds.

        Args:
            context: Request context, for the journals.
            refresh_token: The token naming the session, when there is one.
            session_id: The ``sid`` of the access token, for a client
                holding no refresh token.

        Returns:
            True if a live session was found and retired.
        """
        return self.sign_out_use_case.execute(
            context, refresh_token=refresh_token, session_id=session_id
        )

    def refresh(
        self, refresh_token: str, context: Optional[RequestContext] = None
    ) -> Optional[RefreshedTokens]:
        """Exchange a refresh token for a fresh pair, rotating it.

        Args:
            refresh_token: The token to spend.
            context: Request context. Optional so that callers with no
                request behind them -- a test, a shell -- can still spend
                a token; with one, a replay is recorded.

        Returns:
            The new pair, or None if the token cannot be spent.
        """
        return self.refresh_session_use_case.execute(refresh_token, context)

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
