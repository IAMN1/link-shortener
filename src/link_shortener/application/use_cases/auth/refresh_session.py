from dataclasses import dataclass
from typing import Optional

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.auth import RefreshedTokens
from link_shortener.application.ports.auth.auth_service import (
    AuthenticationService,
)
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain.exceptions import RefreshTokenReplayedError


@dataclass
class RefreshSessionUseCase(BaseUseCase):
    """
    Spends a refresh token, and records the one case worth an alarm.

    Rotation itself needs no use case and this adds none: the token port
    retires the presented token and issues the next pair. What it adds is
    the record for a replay -- a token presented after it had already been
    spent, which means the honest holder and a copy both have it.

    That detection existed and was silent. The chain was retired, ``None``
    was returned, and nothing was written to any journal: the single event
    in this service that means "a credential of this account is loose"
    reached nobody. The refusal the caller sees is unchanged -- the same
    ``None``, answered as the same ``401`` -- because telling the caller
    which of the two failures they hit tells a thief the same thing.

    Attributes:
        authentication_service: The port that rotates and detects.
        audit_logger: Where a replay is recorded.
        logger: The application journal.
    """
    authentication_service: AuthenticationService
    audit_logger: AuditLogger
    logger: Logger

    def execute(
        self,
        refresh_token: str,
        context: Optional[RequestContext] = None,
    ) -> Optional[RefreshedTokens]:
        """
        Exchange a refresh token for a fresh pair.

        Args:
            refresh_token: The token to spend.
            context: Request context, when there is a request behind this.

        Returns:
            The new pair, or ``None`` when the token cannot be spent --
            invalid, expired, already spent, or belonging to an account
            that is gone or switched off.
        """
        try:
            return self.authentication_service.refresh_access_token(
                refresh_token
            )
        except RefreshTokenReplayedError as replay:
            if context is not None:
                audit = self._get_audit_logger(self.audit_logger, context)
                audit.log_refresh_token_replayed(
                    target_user_id=replay.user_id,
                    session_id=replay.chain_id,
                )
                self._get_logger(self.logger, context).warning(
                    "Refresh token replayed; the session chain was retired"
                )
            # The caller is told what every other unusable token is told.
            return None
