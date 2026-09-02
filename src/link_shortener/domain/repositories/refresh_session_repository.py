from abc import ABC, abstractmethod
from typing import Optional

from link_shortener.domain.entities.refresh_session import RefreshSession


class RefreshSessionRepository(ABC):
    """
    Interface for refresh session persistence.

    All methods define what needs to be done without prescribing how; the
    infrastructure layer provides concrete implementations.
    """

    @abstractmethod
    def save(self, session: RefreshSession) -> RefreshSession:
        """
        Persist a new or updated refresh session.

        Args:
            session: RefreshSession entity to save.

        Returns:
            The saved RefreshSession.
        """
        ...

    @abstractmethod
    def find_by_token_id(self, token_id: str) -> Optional[RefreshSession]:
        """
        Find a session by the ``jti`` of its refresh token.

        Args:
            token_id: The token's ``jti`` claim.

        Returns:
            RefreshSession if found, otherwise None.
        """
        ...

    @abstractmethod
    def claim_for_rotation(self, token_id: str, replacement_token_id: str) -> bool:
        """
        Atomically mark a session as spent, if nobody has spent it yet.

        Reading a session, judging it usable and then writing to it leaves a
        window in which a second request does the same, so both are told to
        go ahead and one token yields two live successions. The decision and
        the write have to happen in one conditional statement, and the caller
        must act only when it won.

        Args:
            token_id: Session being spent.
            replacement_token_id: ``token_id`` of the successor.

        Returns:
            True if this caller claimed the session; False if it was already
            revoked, already rotated, or does not exist.
        """
        ...

    # There is deliberately no ``revoke_by_token_id``. One session is not
    # a unit anything here acts on: a login is a chain, however many times
    # its token was rotated, and retiring one link of it leaves the
    # successor live -- so the caller who asked to end a session would
    # have ended nothing. Signing out, a replay and a password change all
    # go through ``revoke_chain`` or ``revoke_all_for_user`` for that
    # reason. The method existed, was implemented, was tested, and was
    # called by nothing.

    @abstractmethod
    def chain_is_live(self, chain_id: str) -> bool:
        """
        Report whether a login is still open.

        Consulted on every authenticated request, because an access token
        carries only a signature and an expiry of its own -- the session
        behind it is the only thing that can say it has been ended.

        Args:
            chain_id: Chain to look up.

        Returns:
            True if the chain has at least one session that is neither
            revoked nor expired.
        """
        ...

    @abstractmethod
    def revoke_chain(self, chain_id: str) -> int:
        """
        Revoke every session in one succession of tokens.

        Used when a spent token comes back: that chain is compromised, but
        the user's other logins are not, so the blast radius stops here.

        Args:
            chain_id: Chain to retire.

        Returns:
            Number of sessions revoked.
        """
        ...

    @abstractmethod
    def revoke_all_for_user(self, user_id: str) -> int:
        """
        Revoke every session belonging to a user.

        Used when an account is blocked.

        Args:
            user_id: Owner of the sessions.

        Returns:
            Number of sessions revoked.
        """
        ...

    @abstractmethod
    def delete_expired(self) -> int:
        """
        Remove sessions whose tokens have expired.

        Housekeeping: expired rows carry no authority and would otherwise
        grow without bound.

        Returns:
            Number of sessions deleted.
        """
        ...
