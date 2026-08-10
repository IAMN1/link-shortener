from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from link_shortener.domain.entities.email_verification import EmailVerification
from link_shortener.domain.repositories.email_verification_repository import (
    EmailVerificationRepository,
)
from link_shortener.infrastructure.database.models.email_verification_model import (
    EmailVerificationModel,
)


class SQLAlchemyEmailVerificationRepository(EmailVerificationRepository):
    """Concrete repository for EmailVerification entities using SQLAlchemy."""

    def __init__(self, session: Session):
        """
        Args:
            session: Active SQLAlchemy session.
        """
        self.session = session

    def save(self, verification: EmailVerification) -> EmailVerification:
        """Insert or update a confirmation.

        Args:
            verification: Domain EmailVerification entity.

        Returns:
            The same entity instance.
        """
        model = self.session.get(EmailVerificationModel, verification.id)
        if not model:
            model = EmailVerificationModel(id=verification.id)
            self.session.add(model)

        model.user_id = verification.user_id
        model.token_hash = verification.token_hash
        model.expires_at = verification.expires_at
        model.created_at = verification.created_at
        model.used_at = verification.used_at

        self.session.flush()
        return verification

    def claim(self, token_hash: str) -> Optional[str]:
        """Spend a confirmation, losing the race gracefully if one is lost.

        The owner is read first and the row is then claimed conditionally,
        so the read is not what decides anything: two callers presenting
        the same link both see a usable row, and the ``UPDATE`` filtered on
        ``used_at IS NULL`` is what only one of them can affect.

        Args:
            token_hash: Digest of the token presented by the caller.

        Returns:
            The account the token confirms, or None if it was unknown,
            already spent, or expired.
        """
        now = datetime.now(timezone.utc)

        owner = (
            self.session.query(EmailVerificationModel.user_id)
            .filter(EmailVerificationModel.token_hash == token_hash)
            .scalar()
        )
        if owner is None:
            return None

        claimed = (
            self.session.query(EmailVerificationModel)
            .filter(
                EmailVerificationModel.token_hash == token_hash,
                EmailVerificationModel.used_at.is_(None),
                EmailVerificationModel.expires_at > now,
            )
            .update(
                {EmailVerificationModel.used_at: now},
                synchronize_session=False,
            )
        )
        self.session.flush()
        return owner if claimed == 1 else None

    def find_by_token_hash(self, token_hash: str) -> Optional[EmailVerification]:
        """Look up a confirmation by the digest of its token.

        Args:
            token_hash: Digest of the token.

        Returns:
            EmailVerification if found, else ``None``.
        """
        model = (
            self.session.query(EmailVerificationModel)
            .filter_by(token_hash=token_hash)
            .first()
        )
        return self._to_domain(model) if model else None

    def invalidate_for_user(self, user_id: str) -> int:
        """Spend every confirmation an account still has outstanding.

        Args:
            user_id: Account whose confirmations are retired.

        Returns:
            Number of confirmations invalidated.
        """
        invalidated = (
            self.session.query(EmailVerificationModel)
            .filter(
                EmailVerificationModel.user_id == user_id,
                EmailVerificationModel.used_at.is_(None),
            )
            .update(
                {EmailVerificationModel.used_at: datetime.now(timezone.utc)},
                synchronize_session=False,
            )
        )
        self.session.flush()
        return invalidated

    def delete_expired(self) -> int:
        """Delete confirmations that can no longer be spent.

        Both halves are swept: expired, and used. A spent confirmation is
        as dead as an expired one and would otherwise sit in the table for
        as long as the account exists.

        Returns:
            Number of rows deleted.
        """
        now = datetime.now(timezone.utc)
        deleted = (
            self.session.query(EmailVerificationModel)
            .filter(
                (EmailVerificationModel.expires_at < now)
                | (EmailVerificationModel.used_at.is_not(None))
            )
            .delete(synchronize_session=False)
        )
        self.session.flush()
        return deleted

    def _to_domain(self, model: EmailVerificationModel) -> EmailVerification:
        """Map an ORM row onto the domain entity.

        Args:
            model: ORM instance.

        Returns:
            Domain EmailVerification.
        """
        return EmailVerification(
            id=model.id,
            user_id=model.user_id,
            token_hash=model.token_hash,
            expires_at=model.expires_at,
            created_at=model.created_at,
            used_at=model.used_at,
        )
