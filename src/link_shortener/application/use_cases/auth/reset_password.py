from dataclasses import dataclass

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.services.user_management_service import (
    UserManagementService,
)
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import ValidationError
from link_shortener.domain.i18n import N_
from link_shortener.domain.value_objects.verification_token import token_digest


@dataclass
class ResetPasswordUseCase(BaseUseCase):
    """
    Spends a reset token and puts a new password behind it.

    Every way a token can fail -- never issued, already spent, expired, or
    belonging to an account that has since been deactivated or swept away
    -- answers the same, as confirmation does. Telling them apart would
    make this route an oracle: "already used" says an account exists and
    somebody reset it, "expired" says one existed recently.

    Nobody is signed in by this. OWASP's Forgot Password Cheat Sheet asks
    for it -- the person is sent to the sign-in page and uses the password
    they just chose -- and it is the honest order: the account has just
    been opened by a link out of a mailbox, and the first thing it should
    ask for is the credential.

    Every session goes, and that is the whole point rather than tidiness.
    The ordinary reason to reset a password is that somebody else may have
    it, and a reset that leaves their session open has changed nothing
    they care about.

    Attributes:
        uow_factory: Factory for Unit of Work instances.
        user_service: Hashes the new password and writes it to the account.
        logger: Application logger.
        audit_logger: Audit logger, where the reset is recorded.
    """
    uow_factory: UnitOfWorkFactory
    user_service: UserManagementService
    logger: Logger
    audit_logger: AuditLogger

    def execute(
        self, token: str, new_password: str, context: RequestContext
    ) -> None:
        """
        Replace one account's password on the strength of a mailed token.

        Args:
            token: The token from the reset link.
            new_password: What to set the password to.
            context: Request context.

        Raises:
            ValidationError: If the token cannot be spent, for any reason,
                or if the new password is refused by the password policy.
        """
        log = self._get_logger(self.logger, context)
        audit = self._get_audit_logger(self.audit_logger, context)

        with self.uow_factory() as uow:
            # claim() reads the owner and then spends the row with a
            # conditional UPDATE. The second statement is what decides:
            # filtered on ``used_at IS NULL``, only one of two requests
            # carrying the same link can affect a row.
            user_id = uow.password_resets.claim(token_digest(token))
            if user_id is None:
                log.warning("Password reset refused")
                raise ValidationError(
                    N_("This reset link is not valid"), field="token"
                )

            user = uow.users.find_by_id(user_id)
            if user is None or not user.is_active:
                # Gone or switched off between the issue and now. Raising
                # rolls the transaction back, the claim included, so the
                # token is not spent -- which is harmless, because the next
                # attempt fails at this same line.
                log.warning("Password reset names an account it cannot open")
                raise ValidationError(
                    N_("This reset link is not valid"), field="token"
                )

            # Before the password is written, so that a password the policy
            # refuses leaves nothing behind: the raise rolls back the claim
            # with it, and the link the person is holding still works for
            # their second attempt at a strong enough password.
            self.user_service.update_password(uow, user, new_password)

            # The other links this account may still have outstanding. One
            # of them is quite possibly the reason this reset happened, and
            # a link that survives the reset it caused survives the point
            # of it.
            uow.password_resets.invalidate_for_user(user.id)

            revoked = uow.refresh_sessions.revoke_all_for_user(user.id)

            uow.commit()

        log.info("Password reset", user_id=user.id, sessions_revoked=revoked)
        audit.log_password_reset(
            target_user_id=user.id, sessions_revoked=revoked
        )
