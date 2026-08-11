from dataclasses import dataclass
from typing import Callable

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import ValidationError
from link_shortener.domain.value_objects.verification_token import token_digest


@dataclass
class VerifyEmailUseCase(BaseUseCase):
    """
    Spends a confirmation token and marks the address as proven.

    Every way a token can fail -- never issued, already spent, expired,
    or belonging to an account that has since been swept away -- answers
    the same. Telling them apart would turn this route into an oracle:
    "already used" says an account exists and someone confirmed it,
    "expired" says one existed recently.

    Attributes:
        uow_factory: Factory for Unit of Work instances.
        logger: Application logger.
    """
    uow_factory: Callable[[], UnitOfWork]
    logger: Logger

    def execute(self, token: str, context: RequestContext) -> None:
        """
        Confirm the address a token was issued for.

        Args:
            token: The token from the confirmation link.
            context: Request context.

        Raises:
            ValidationError: If the token cannot be spent, for any reason.
        """
        log = self._get_logger(self.logger, context)

        with self.uow_factory() as uow:
            # claim() reads the owner and then spends the row with a
            # conditional UPDATE -- two statements, and the second is what
            # decides: filtered on ``used_at IS NULL``, only one of two
            # requests carrying the same link can affect a row.
            user_id = uow.email_verifications.claim(token_digest(token))
            if user_id is None:
                log.warning("Email confirmation refused")
                raise ValidationError(
                    "This confirmation link is not valid", field="token"
                )

            user = uow.users.find_by_id(user_id)
            if user is None:
                # The account went away between the claim and this read --
                # the sweep, or an administrator, in another transaction.
                # Only reachable as a race: the foreign key refuses a
                # confirmation for an account that does not exist, and
                # ``ON DELETE CASCADE`` takes the confirmations with the
                # account.
                #
                # Raising here rolls the whole transaction back, the claim
                # included, so the token is *not* spent. That is harmless
                # -- it names an account that is gone, so the next attempt
                # fails at this same line -- and it is stated because an
                # earlier version of this comment claimed the opposite.
                log.warning("Email confirmation names a missing account")
                raise ValidationError(
                    "This confirmation link is not valid", field="token"
                )

            user.confirm_email()
            uow.users.save(user)
            uow.commit()

        log.info("Email confirmed", user_id=user_id)
