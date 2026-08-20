from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from link_shortener.domain.entities.refresh_session import RefreshSession
from link_shortener.domain.repositories.refresh_session_repository import (
    RefreshSessionRepository,
)
from link_shortener.infrastructure.database.models.refresh_session_model import (
    RefreshSessionModel,
)


class SQLAlchemyRefreshSessionRepository(RefreshSessionRepository):
    """Concrete repository for RefreshSession entities using SQLAlchemy."""

    def __init__(self, session: Session):
        """
        Args:
            session: Active SQLAlchemy session.
        """
        self.session = session

    def save(self, refresh_session: RefreshSession) -> RefreshSession:
        """Insert or update a refresh session.

        Args:
            refresh_session: Domain RefreshSession entity.

        Returns:
            The same entity instance.
        """
        model = self.session.get(RefreshSessionModel, refresh_session.id)
        if not model:
            model = RefreshSessionModel(id=refresh_session.id)
            self.session.add(model)

        model.user_id = refresh_session.user_id
        model.token_id = refresh_session.token_id
        model.chain_id = refresh_session.chain_id
        model.expires_at = refresh_session.expires_at
        model.created_at = refresh_session.created_at
        model.revoked_at = refresh_session.revoked_at
        model.replaced_by = refresh_session.replaced_by

        self.session.flush()
        return refresh_session

    def claim_for_rotation(self, token_id: str, replacement_token_id: str) -> bool:
        """Spend a session, losing the race gracefully if someone got there first.

        Args:
            token_id: Session being spent.
            replacement_token_id: ``token_id`` of the successor.

        Returns:
            True if this caller claimed it.
        """
        claimed = (
            self.session.query(RefreshSessionModel)
            .filter(
                RefreshSessionModel.token_id == token_id,
                RefreshSessionModel.revoked_at.is_(None),
                RefreshSessionModel.replaced_by.is_(None),
                RefreshSessionModel.expires_at > datetime.now(timezone.utc),
            )
            .update(
                {RefreshSessionModel.replaced_by: replacement_token_id},
                synchronize_session=False,
            )
        )
        self.session.flush()
        return claimed == 1

    def chain_is_live(self, chain_id: str) -> bool:
        """Report whether a chain still has a usable session.

        Args:
            chain_id: Chain to look up.

        Returns:
            True if at least one session is neither revoked nor expired.
        """
        return (
            self.session.query(RefreshSessionModel.id)
            .filter(
                RefreshSessionModel.chain_id == chain_id,
                RefreshSessionModel.revoked_at.is_(None),
                RefreshSessionModel.expires_at > datetime.now(timezone.utc),
            )
            .first()
            is not None
        )

    def revoke_chain(self, chain_id: str) -> int:
        """Revoke every live session in one chain.

        Args:
            chain_id: Chain to retire.

        Returns:
            Number of sessions revoked.
        """
        revoked = (
            self.session.query(RefreshSessionModel)
            .filter(
                RefreshSessionModel.chain_id == chain_id,
                RefreshSessionModel.revoked_at.is_(None),
            )
            .update(
                {RefreshSessionModel.revoked_at: datetime.now(timezone.utc)},
                synchronize_session=False,
            )
        )
        self.session.flush()
        return revoked

    def find_by_token_id(self, token_id: str) -> Optional[RefreshSession]:
        """Look up a session by its token's ``jti``.

        Args:
            token_id: The token's ``jti`` claim.

        Returns:
            RefreshSession entity if found, else ``None``.
        """
        model = (
            self.session.query(RefreshSessionModel)
            .filter_by(token_id=token_id)
            .first()
        )
        return self._to_domain(model) if model else None

    def revoke_all_for_user(self, user_id: str) -> int:
        """Revoke every session of a user that is still live.

        Args:
            user_id: Owner of the sessions.

        Returns:
            Number of sessions revoked.
        """
        revoked = (
            self.session.query(RefreshSessionModel)
            .filter(
                RefreshSessionModel.user_id == user_id,
                RefreshSessionModel.revoked_at.is_(None),
            )
            .update(
                {RefreshSessionModel.revoked_at: datetime.now(timezone.utc)},
                synchronize_session=False,
            )
        )
        self.session.flush()
        return revoked

    def delete_expired(self) -> int:
        """Delete sessions whose tokens have already expired.

        Returns:
            Number of sessions deleted.
        """
        deleted = (
            self.session.query(RefreshSessionModel)
            .filter(RefreshSessionModel.expires_at < datetime.now(timezone.utc))
            .delete(synchronize_session=False)
        )
        self.session.flush()
        return deleted

    def _to_domain(self, model: RefreshSessionModel) -> RefreshSession:
        """Map an ORM row onto the domain entity.

        Args:
            model: ORM instance.

        Returns:
            Domain RefreshSession.
        """
        return RefreshSession(
            id=model.id,
            user_id=model.user_id,
            token_id=model.token_id,
            chain_id=model.chain_id,
            expires_at=model.expires_at,
            created_at=model.created_at,
            revoked_at=model.revoked_at,
            replaced_by=model.replaced_by,
        )
