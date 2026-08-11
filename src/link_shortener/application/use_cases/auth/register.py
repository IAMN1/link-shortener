from dataclasses import dataclass
from typing import Callable

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.auth.auth_service import AuthenticationService
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.task_queue import TaskQueue
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import (
    DomainError, User,
    Email, PasswordHash
)
from link_shortener.domain.entities.email_verification import EmailVerification
from link_shortener.domain.value_objects.verification_token import (
    issue_token,
    token_digest,
)


@dataclass
class RegisterUseCase(BaseUseCase):
    """
    Creates a new user account with the default role.

    The password is hashed by the AuthenticationService before storage.

    The account starts unconfirmed and cannot sign in until the address is
    proven readable. The confirmation is issued in the same transaction as
    the account, so there is no state where one exists without the other,
    and handed to the queue afterwards -- a message cannot be sent for a
    row that has not been committed yet.

    A message that fails to go out does not undo the registration. The
    account and its token are already stored, so the person can ask for
    another one; rolling back instead would make the mail server able to
    stop registration outright, and would tell an anonymous caller that it
    is down.

    An address that is already registered is not refused out loud. It used
    to be -- 400 and "Email already registered" -- which answered, for
    anyone who cared to ask, whether an address has an account here.
    OWASP's Authentication Cheat Sheet lists that under *Account creation*
    as an incorrect response, alongside a plain "Welcome! You have signed
    up successfully."; the correct one it gives is "A link to activate
    your account has been emailed to the address provided." Both paths now
    return the same nothing, and the controller turns that into one
    answer.

    Equal answers are half of it. The other half is that they take the
    same time to produce, which is what the order of operations here is
    for. Hashing used to happen after the existence check, so a taken
    address short-circuited before bcrypt and came back in 0.56 ms against
    162.52 ms for a free one -- 290x, with the two ranges nowhere near
    each other, so one request was enough to tell them apart. The hash is
    now computed before anything is looked up, which is the shape OWASP's
    Forgot Password Cheat Sheet asks for: "Ensure that responses return in
    a consistent amount of time... instead of using a quick exit method."

    Mail is the other half of the clock. Registration submits one message
    either way -- a confirmation link for a free address, a notice for a
    taken one -- because without a broker the submission happens on the
    request thread, and a path that skipped it would be shorter by the
    length of an SMTP exchange (13-15 ms against a local catcher; a remote
    relay is slower). See ``SendAccountExistsEmailUseCase`` for what that
    notice may and may not say.

    What stays different is the writing: a free address inserts two rows
    and commits, a taken one does not. That is a real remainder, small
    beside a bcrypt hash, and it is measured and written down in the
    developer guide rather than claimed away here.
    """
    uow_factory: Callable[[], UnitOfWork]
    authentication_service: AuthenticationService
    logger: Logger
    default_role_name: str  # Role assigned to new users by default.
    task_queue: TaskQueue
    verification_ttl_hours: int

    def execute(self, email: str, password: str, context: RequestContext) -> None:
        """
        Register a new user, or say nothing about one that exists.

        Args:
            email: Desired email.
            password: Plain-text password.
            context: Request context.

        Returns:
            Nothing. The caller cannot be told which of the two happened,
            so there is nothing to hand back -- an identifier here would
            be the disclosure this method exists to avoid.

        Raises:
            ValidationError: If the email is not an address, or the
                password does not meet the policy. Both are refused out
                loud because both are properties of what the caller sent,
                not of who is registered.
        """
        log = self._get_logger(self.logger, context)
        log.info("Registration attempt", email=email)

        # Validate email using domain value object
        email_vo = Email(email)

        # Hashed before the lookup, not after. This is the expensive step
        # -- ~160 ms of bcrypt -- and whichever branch skipped it would be
        # the one an attacker could recognise by the clock alone. Password
        # policy is enforced in here too, so a password the policy refuses
        # is refused for a taken address exactly as for a free one.
        hashed = self.authentication_service.hash_password(password)
        password_hash_vo = PasswordHash(hashed)

        saved_user = None
        token = None
        with self.uow_factory() as uow:

            # Check for existing user. A taken address writes nothing and
            # reads nothing further; what it produces -- a message to the
            # address -- is handed off below, outside this block, for the
            # same reason the confirmation is: without a broker the
            # hand-off is the SMTP exchange itself, and making it here
            # would hold a database connection open across a network call.
            if uow.users.find_by_email(email_vo) is None:

                # Retrieve default role
                default_role = uow.roles.get_by_name(self.default_role_name)
                if not default_role:
                    log.error(
                        "Default role not found", role_name=self.default_role_name
                    )
                    # A server failure in substance: the caller did nothing
                    # wrong and retrying with different input will not help.
                    # The message says so and no longer names the missing
                    # role, which told an anonymous caller which part of the
                    # deployment is misconfigured.
                    #
                    # The status is still 400, because the controller answers
                    # every DomainError that way -- so the code, not the
                    # status, is what distinguishes this from a bad request.
                    #
                    # It is also the one place the two paths still diverge:
                    # a deployment missing its default role answers 400 for
                    # a free address and 202 for a taken one. That is a
                    # deployment which cannot register anybody at all.
                    raise DomainError(
                        "Registration is unavailable",
                        code="CONFIGURATION_ERROR",
                    )

                # Create user entity
                user = User.create(
                    email=email_vo,
                    password_hash=password_hash_vo,
                    roles=[default_role]
                )

                saved_user = uow.users.save(user)

                token = issue_token()
                uow.email_verifications.save(
                    EmailVerification.issue(
                        user_id=saved_user.id,
                        token_hash=token_digest(token),
                        ttl_hours=self.verification_ttl_hours,
                    )
                )
                uow.commit()

        if saved_user is None:
            # Recorded, because a run of these is somebody walking a list
            # of addresses, and answered exactly like a success. The notice
            # is what the owner of the address gets instead of the caller
            # getting an answer.
            log.info("Registration attempt on a registered address")
            # Sent to the normalised address, which is the one the
            # account is stored under. Mailing the string as typed would
            # send to an address the service does not recognise as its own.
            if not self.task_queue.enqueue_account_exists_email(
                email_vo.value, context
            ):
                log.error(
                    "Account-exists notice was not handed off",
                    email=email_vo.value,
                )
            return None

        log.info("User registered", user_id=saved_user.id, email=email_vo.value)

        if not self.task_queue.enqueue_verification_email(
            email_vo.value, token, context
        ):
            # Said out loud rather than swallowed: the account exists and
            # cannot be used, and nobody will find out from the response,
            # which is the same either way.
            log.error(
                "Registered account has no confirmation message",
                user_id=saved_user.id,
                email=email_vo.value,
            )

        return None
