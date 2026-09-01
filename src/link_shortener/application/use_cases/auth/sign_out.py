from dataclasses import dataclass
from typing import Optional

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.auth.auth_service import (
    AuthenticationService,
)
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.use_cases.base_use_case import BaseUseCase


@dataclass
class SignOutUseCase(BaseUseCase):
    """
    Ends one session and puts it on the record.

    Signing out had no use case: the controller reached the token port
    directly, on the grounds -- written at ``AuthService`` -- that there is
    "no policy in either beyond retiring a session". Recording the act is
    policy, and its absence was measured: a run that revoked eleven
    sessions left ``grep -ci 'LOGOUT\\|SESSION_REVOKED'`` at zero across
    all three journals, so the journal could show a sign-in with no end
    and an account with no open session at the same time.

    The rule the vocabulary follows says why it belongs there: an act that
    changes who may do what leaves a record, and a session ceasing is
    exactly that -- it is what makes the access tokens issued along the
    chain stop working.

    Only the chain presented is retired. The account's other devices have
    chains of their own, and ending them from here would make signing out
    of one browser a way to sign somebody out of everything.

    Attributes:
        authentication_service: The port that retires sessions.
        uow_factory: Opens the read the record needs -- which chain the
            presented refresh token belongs to. The token itself cannot
            say: ``sid`` is a claim of an access token, and a refresh
            token carries ``jti``, the row.
        audit_logger: Where the act is recorded.
        logger: The application journal.
    """
    authentication_service: AuthenticationService
    uow_factory: UnitOfWorkFactory
    audit_logger: AuditLogger
    logger: Logger

    def execute(
        self,
        context: RequestContext,
        refresh_token: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> bool:
        """
        Retire the session the caller names, and record it.

        Args:
            context: Request context, for the journal fields.
            refresh_token: The refresh token, when the client holds one.
            session_id: The chain from the access token, for a client that
                holds only that. Used when no refresh token was sent.

        Returns:
            True when a live session was found and retired. False is the
            ordinary answer to signing out twice, and is not an error: the
            caller wanted no session and has none.
        """
        log = self._get_logger(self.logger, context)
        audit = self._get_audit_logger(self.audit_logger, context)

        target_user_id: Optional[str] = None
        chain: Optional[str] = session_id

        if refresh_token:
            # Read before the revocation rather than after it, because the
            # row is what names the chain and the revocation retires it.
            #
            # The account comes off the token; the chain does not. A
            # refresh token carries ``jti``, which names its row, while
            # ``sid`` -- the chain -- is a claim of an *access* token. So
            # the chain is looked up by ``jti``. Measured before this:
            # signing out with a refresh token and no access token wrote
            # ``SESSION_ENDED ... session_id=None``, which is the one field
            # that tells an investigator which login ended. Through a
            # browser the field was filled, because the controller also
            # passes the ``sid`` it has -- so the hole was open exactly for
            # the client whose access token had expired, which is the
            # ordinary reason to be holding only a refresh token.
            claims = self.authentication_service.validate_token(
                refresh_token, expected_type="refresh"
            )
            if claims:
                target_user_id = claims.get("sub")
                token_id = claims.get("jti")
                if chain is None and token_id:
                    with self.uow_factory(read_only=True) as uow:
                        row = uow.refresh_sessions.find_by_token_id(token_id)
                        if row is not None:
                            chain = row.chain_id
            ended = self.authentication_service.revoke_refresh_token(
                refresh_token
            )
        elif session_id:
            target_user_id = (
                context.current_user.id if context.current_user else None
            )
            ended = self.authentication_service.revoke_session_chain(
                session_id
            ) > 0
        else:
            return False

        if not ended:
            # Nothing was open. Recorded in the application journal, which
            # is where "somebody asked and there was nothing there" belongs;
            # the security journal is for acts that happened.
            log.info("Sign-out found no live session")
            return False

        audit.log_session_ended(target_user_id=target_user_id, session_id=chain)
        return True
