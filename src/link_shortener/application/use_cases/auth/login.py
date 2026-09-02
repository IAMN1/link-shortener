import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.auth import LoginResponse
from link_shortener.application.dtos.user import UserResponse
from link_shortener.application.ports.auth.auth_service import AuthenticationService
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.rate_limiter import RateLimiter
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import DomainError
from link_shortener.domain.value_objects.email import Email
from link_shortener.domain.i18n import N_


@dataclass
class LoginUseCase(BaseUseCase):
    """
    Authenticates a user by email and password.

    On success, generates an access token and a refresh token, and returns
    the user's profile. Raises a ``DomainError`` if the credentials are
    invalid, the account is inactive, or its address has not been
    confirmed. Only the last of the three says which it was.

    All four outcomes reach the audit journal, and the refusals reach it
    named -- which is the opposite of what the caller is told. The response
    conflates a wrong password with a deactivated account so that a guesser
    learns nothing from the difference; the journal separates them so that
    an operator can. What makes the two safe to hold apart is that they are
    read through different doors: the response goes to whoever asked, the
    journal opens to ``audit:view``.

    Attributes:
        authentication_service: Checks the credentials and opens sessions.
        logger: Application logger.
        uow_factory: Callable that returns a new Unit of Work instance.
        audit_logger: Audit logger, where the outcome is recorded.
        rate_limiter: Where the per-account failure budget is counted.
        account_failure_limit: Wrong guesses one address may make inside
            the window; zero disables the budget.
        account_failure_period: The window, in seconds.
    """
    authentication_service: AuthenticationService
    logger: Logger
    uow_factory: UnitOfWorkFactory
    audit_logger: AuditLogger
    rate_limiter: RateLimiter
    account_failure_limit: int
    account_failure_period: int

    def _failure_key(self, email: str) -> str:
        """
        Build the counter key for an address without storing the address.

        The key lives in Redis, which is not where a list of this
        service's users belongs -- the journals already hold addresses,
        behind a permission, and a cache key is behind none. A digest
        answers the only question the counter asks, "is this the same
        address as last time", and answers nothing else.

        Normalised first, through the value object that owns the rule, so
        that ``Case@Example.com`` and ``case@example.com`` spend one
        budget rather than two. Done here rather than by constructing an
        ``Email``: this runs before validation, and an address that turns
        out to be malformed still has to be counted -- otherwise the
        cheapest way past the budget is to keep the address invalid.

        Args:
            email: The address as the caller typed it.

        Returns:
            A stable key for this address.
        """
        digest = hashlib.sha256(
            Email.normalise(email or "").encode("utf-8")
        ).hexdigest()

        return f"login-failure:{digest}"

    def _budget_spent(self, email: str) -> bool:
        """
        Report whether this address has spent its failure budget.

        Asks without recording: the check happens on every attempt, and a
        check that counted would spend the budget on the successful ones
        too.

        Args:
            email: The address the attempt is against.

        Returns:
            ``True`` when the account should be refused without the
            password being looked at.
        """
        if self.account_failure_limit <= 0:
            return False

        return self.rate_limiter.get_remaining(
            self._failure_key(email),
            self.account_failure_limit,
            self.account_failure_period,
        ) <= 0

    def _spend_budget(self, email: str) -> None:
        """
        Record one wrong guess against this address.

        Args:
            email: The address the attempt was against.
        """
        if self.account_failure_limit <= 0:
            return

        self.rate_limiter.is_allowed(
            self._failure_key(email),
            self.account_failure_limit,
            self.account_failure_period,
        )

    def execute(
        self, email: str, password: str, context: RequestContext
    ) -> LoginResponse:
        """
        Perform login.

        Args:
            email: Registered email.
            password: Plain-text password.
            context: Request context containing client metadata.

        Returns:
            LoginResponse with tokens and user data.

        Raises:
            DomainError: If authentication fails. A deactivated account is
                reported as invalid credentials so that the response does
                not distinguish the two cases.
        """
        log = self._get_logger(self.logger, context)
        audit = self._get_audit_logger(self.audit_logger, context)
        log.info("Login attempt", email=email)

        # Before the password is looked at, and deliberately not by
        # sleeping. A growing delay is the textbook answer and it cannot be
        # had here: gunicorn runs synchronous workers, so a sleeping
        # request holds one, and four held workers are the whole service --
        # the same exhaustion `MAX_CONTENT_LENGTH` exists to stop, invited
        # in through the front door. Refusing costs nothing and slows a
        # guesser by the same amount.
        #
        # Answered exactly like a wrong password, as every other refusal on
        # this route is: saying "too many attempts" would name an address
        # somebody is interested in, and the budget is spent by addresses
        # that name no account at all, so the two must not be told apart.
        if self._budget_spent(email):
            log.warning("Login refused: account failure budget spent")
            audit.log_login_failed(email=email, reason="too_many_failures")
            raise DomainError(
                N_("Invalid email or password"), code="INVALID_CREDENTIALS"
            )

        user = self.authentication_service.authenticate(email, password)
        if not user:
            # Only here. The two refusals below arrive with the *right*
            # password, so they are not guesses, and spending an account's
            # budget on them would let anyone holding a valid credential
            # lock out the account it belongs to.
            self._spend_budget(email)
            log.warning("Login failed", email=email)
            # No user id: nothing was authenticated, and the address is all
            # there is to say who the attempt was against. Whether it names
            # an account at all is a question this record deliberately does
            # not answer -- the same refusal covers both, here as in the
            # response.
            audit.log_login_failed(email=email, reason="invalid_credentials")
            raise DomainError(N_("Invalid email or password"), code="INVALID_CREDENTIALS")

        if not user.is_active:
            # Answered exactly like a wrong password. Saying "deactivated"
            # only when the password is right confirms both that the account
            # exists and that the password guess landed.
            log.warning("Login attempt on inactive user", user_id=user.id)
            # The journal is told which it was, and the account too: the
            # password was right, so this is a live credential being used
            # against an account somebody switched off -- the one refusal
            # here that says an intrusion may already have happened.
            audit.log_login_failed(
                email=email,
                reason="account_deactivated",
                target_user_id=user.id,
            )
            raise DomainError(N_("Invalid email or password"), code="INVALID_CREDENTIALS")

        if not user.email_verified:
            # Answered exactly like a wrong password, as the two branches
            # above are.
            #
            # It used to be named, and the argument for naming it was
            # about account *existence*: the only caller who reaches this
            # line already knows the password, so telling them the address
            # is unconfirmed reveals no account they had not already
            # found. That much is true, and it is not what the answer
            # costs. What it reveals is that the guess **landed** -- and a
            # password is worth having away from this service, because
            # people use the same one in several places. Measured on a
            # live stack: `EMAIL_NOT_VERIFIED` came back for the right
            # password and `INVALID_CREDENTIALS` for a wrong one, so the
            # pair is an oracle that answers "is this the password" to
            # anybody willing to try. Every other refusal this service
            # makes is deliberately uniform -- registration does not say
            # whether an address is taken, a reset answers the same for an
            # address it has never seen -- and this was the one place that
            # was not.
            #
            # The holder is not stranded by the change: the sign-in page
            # carries "Didn't get the confirmation email?" at all times,
            # not only after a refusal, and `resend-verification` answers
            # 202 whatever address it is given. So the way back exists,
            # is visible without being told, and reveals nothing either.
            log.warning("Login attempt on unverified user", user_id=user.id)
            # The journal keeps the distinction the wire drops, which is
            # the arrangement `log_login_failed` was written for: an
            # operator has to tell "somebody is guessing" from "a real
            # user never confirmed", and `audit:view` is what separates
            # that reader from the caller.
            audit.log_login_failed(
                email=email,
                reason="email_not_verified",
                target_user_id=user.id,
            )
            raise DomainError(
                N_("Invalid email or password"), code="INVALID_CREDENTIALS"
            )

        # One column, by a conditional update, rather than saving the
        # entity back. The entity was read to check the password, which is
        # ~160 ms of bcrypt ago, and `save` writes every column it holds:
        # an account an administrator switched off during that window came
        # back active, and a password changed during it was replaced by
        # the old hash -- so the new password stopped working and the one
        # the change was made against went on working. The rule is
        # `JwtAuthenticationService.revoke_refresh_token`'s, applied here.
        user.last_login = datetime.now(timezone.utc)
        with self.uow_factory() as uow:
            uow.users.record_login(user.id, user.last_login)
            uow.commit()

        # Open a session and take its pair of tokens.
        tokens = self.authentication_service.create_session_tokens(user)

        log.info("login successful", user_id=user.id, email=user.email.value)

        # After the session exists, not before: a record written ahead of
        # `create_session_tokens` would claim a sign-in that a failure in
        # it never completed.
        audit.log_login_succeeded(
            target_user_id=user.id, email=user.email.value
        )

        user_dto = UserResponse.from_user(user)
        return LoginResponse(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            user=user_dto,
        )
