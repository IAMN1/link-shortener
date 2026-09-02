from dataclasses import dataclass

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.auth import RefreshedTokens
from link_shortener.application.ports.auth.auth_service import AuthenticationService
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.services.user_management_service import (
    UserManagementService,
)
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import DomainError, ValidationError
from link_shortener.domain.i18n import N_


@dataclass
class ChangePasswordUseCase(BaseUseCase):
    """
    Replaces the password of the account that is asking, and only that one.

    The current password is required and checked here rather than taken on
    the session's word. A session is what somebody who borrowed the laptop
    or landed a script on the page already holds, and without this check
    the password is theirs to change -- which locks the owner out of their
    own account and is the one move that turns a stolen session into a
    stolen account. ASVS 2.1.5 asks for exactly this, and the cost of it
    is one bcrypt comparison.

    Every session the account has goes with the change, this one included,
    and a fresh pair is issued to the caller afterwards. The alternative --
    leaving the current session untouched -- reads the same from the
    outside but is not the same act: the sessions are revoked first and the
    new pair is opened after, so there is no moment at which a session
    predating the change is still valid. What the caller keeps is a session
    younger than the new password, granted on the strength of the old one
    they just proved they knew.

    Attributes:
        uow_factory: Factory for Unit of Work instances.
        authentication_service: Compares passwords and opens sessions.
        user_service: Hashes the new password and writes it to the account.
        logger: Application logger.
        audit_logger: Audit logger, where the change is recorded.
    """
    uow_factory: UnitOfWorkFactory
    authentication_service: AuthenticationService
    user_service: UserManagementService
    logger: Logger
    audit_logger: AuditLogger

    def execute(
        self,
        user_id: str,
        current_password: str,
        new_password: str,
        context: RequestContext,
    ) -> RefreshedTokens:
        """
        Replace one account's password and re-open its session.

        Args:
            user_id: The account making the request, as authenticated.
            current_password: The password it is signed in with.
            new_password: What to replace it with.
            context: Request context.

        Returns:
            A fresh pair of tokens for the caller, opened after every
            earlier session was revoked.

        Raises:
            ValidationError: If the current password does not match, if the
                new one repeats it, or if the new one is refused by the
                password policy.
            DomainError: If the account has gone away since it was
                authenticated.
        """
        log = self._get_logger(self.logger, context)
        audit = self._get_audit_logger(self.audit_logger, context)

        with self.uow_factory() as uow:
            user = uow.users.find_by_id(user_id)
            if user is None:
                # Authenticated a moment ago and gone now: deleted in
                # another transaction between the middleware's read and
                # this one. Answered as an unauthenticated request, which
                # is what the caller now is.
                log.warning("Password change names a missing account")
                raise DomainError(
                    N_("Authentication required"), code="UNAUTHENTICATED"
                )

            if not self.authentication_service.verify_password(
                current_password, user.password_hash.value
            ):
                # Named plainly, unlike a refused sign-in. The two hide
                # different things: a sign-in must not say whether the
                # account exists, and here the caller is already inside it.
                # What is left to conceal is nothing, and "something was
                # wrong with the form" would send them to re-read the new
                # password they typed correctly.
                log.warning("Password change refused", user_id=user.id)
                raise ValidationError(
                    N_("Current password is not correct"),
                    field="current_password",
                )

            if self.authentication_service.verify_password(
                new_password, user.password_hash.value
            ):
                # A change that changes nothing still revokes every session
                # and still writes an audit record saying the password was
                # replaced. Both would be false.
                raise ValidationError(
                    N_("The new password must differ from the current one"),
                    field="new_password",
                )

            # The whole act in one call: hashing, the policy that refuses
            # a weak password, the reset links this change retires, and
            # the sessions it closes. All of it lives in the service so
            # that the operator's command-line path cannot do a part of
            # it -- which it did, replacing the hash and leaving every
            # session live.
            #
            # Before the commit, and before any new session exists: a
            # session opened first would be revoked in here, and the
            # caller would be signed out by the change they made.
            revoked = self.user_service.update_password(
                uow, user, new_password
            )

            uow.commit()

        # Outside the transaction, as the sign-in does it: the session
        # writes its own row, and nesting it inside this unit of work would
        # make the password change wait on it.
        tokens = self.authentication_service.create_session_tokens(user)

        log.info("Password changed", user_id=user.id, sessions_revoked=revoked)
        audit.log_password_changed(
            target_user_id=user.id, sessions_revoked=revoked
        )

        return tokens
