from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from link_shortener.domain.entities.password_reset import PasswordReset
from link_shortener.domain.repositories.password_reset_repository import (
    PasswordResetRepository,
)
from link_shortener.infrastructure.database.models.password_reset_model import (
    PasswordResetModel,
)


class SQLAlchemyPasswordResetRepository(PasswordResetRepository):
    """Concrete repository for PasswordReset entities using SQLAlchemy."""

    def __init__(self, session: Session):
        """
        Args:
            session: Active SQLAlchemy session.
        """
        self.session = session

    def save(self, reset: PasswordReset) -> PasswordReset:
        """Insert or update a reset token.

        Args:
            reset: Domain PasswordReset entity.

        Returns:
            The same entity instance.
        """
        model = self.session.get(PasswordResetModel, reset.id)
        if not model:
            model = PasswordResetModel(id=reset.id)
            self.session.add(model)

        model.user_id = reset.user_id
        model.token_hash = reset.token_hash
        model.expires_at = reset.expires_at
        model.created_at = reset.created_at
        model.used_at = reset.used_at

        self.session.flush()
        return reset

    def claim(self, token_hash: str) -> Optional[str]:
        """Spend a reset token, losing the race gracefully if one is lost.

        The owner is read first and the row is then claimed conditionally,
        so the read decides nothing: two callers presenting the same link
        both see a usable row, and the ``UPDATE`` filtered on
        ``used_at IS NULL`` is what only one of them can affect.

        Args:
            token_hash: Digest of the token presented by the caller.

        Returns:
            The account the token belongs to, or None if it was unknown,
            already spent, or expired.
        """
        now = datetime.now(timezone.utc)

        owner = (
            self.session.query(PasswordResetModel.user_id)
            .filter(PasswordResetModel.token_hash == token_hash)
            .scalar()
        )
        if owner is None:
            return None

        claimed = (
            self.session.query(PasswordResetModel)
            .filter(
                PasswordResetModel.token_hash == token_hash,
                PasswordResetModel.used_at.is_(None),
                PasswordResetModel.expires_at > now,
            )
            .update(
                {PasswordResetModel.used_at: now},
                synchronize_session=False,
            )
        )
        self.session.flush()
        return owner if claimed == 1 else None

    def invalidate_for_user(self, user_id: str) -> int:
        """Spend every reset token an account still has outstanding.

        Args:
            user_id: Account whose tokens are retired.

        Returns:
            Number of tokens invalidated.
        """
        invalidated = (
            self.session.query(PasswordResetModel)
            .filter(
                PasswordResetModel.user_id == user_id,
                PasswordResetModel.used_at.is_(None),
            )
            .update(
                {PasswordResetModel.used_at: datetime.now(timezone.utc)},
                synchronize_session=False,
            )
        )
        self.session.flush()
        return invalidated

    def delete_expired(self) -> int:
        """Delete tokens that can no longer be spent.

        Both halves are swept: expired, and used. A spent token is as dead
        as an expired one and would otherwise sit in the table for as long
        as the account exists.

        Returns:
            Number of rows deleted.
        """
        now = datetime.now(timezone.utc)
        deleted = (
            self.session.query(PasswordResetModel)
            .filter(
                (PasswordResetModel.expires_at < now)
                | (PasswordResetModel.used_at.is_not(None))
            )
            .delete(synchronize_session=False)
        )
        self.session.flush()
        return deleted
