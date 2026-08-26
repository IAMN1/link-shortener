from typing import List
from sqlalchemy.orm import Session

from link_shortener.infrastructure.database.models.permission_model import PermissionModel
from link_shortener.domain import Permission, PermissionRepository


class SQLAlchemyPermissionRepository(PermissionRepository):
    """
    Concrete repository for Permission entities using SQLAlchemy.

        Uses the session provided at construction time; all operations are
        scoped to that session.
    """
    def __init__(self, session: Session):
        """
        Args:
            session: Active SQLAlchemy session.
        """
        self.session = session

    def get_by_names(self, names: List[str]) -> List[Permission]:
        """
        Retrieve permissions by their unique names.

        If a name is not found, it is silently omitted from the result.

        Args:
            names: List of permission names (e.g., ``["link:create"]``).

        Returns:
            List of Permission entities matching the given names.
        """
        if not names:
            return []
        
        models = self.session.query(PermissionModel).filter(
            PermissionModel.name.in_(names)
        ).all()
        
        return [self._to_domain(m) for m in models]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------
    def _to_domain(self, model: PermissionModel) -> Permission:
        """
        Convert ORM model to domain Permission.

        Args:
            model: PermissionModel instance.

        Returns:
            Domain Permission entity.
        """
        return Permission(
            id=model.id,
            name=model.name,
            resource=model.resource,
            action=model.action,
            description=model.description
        )
