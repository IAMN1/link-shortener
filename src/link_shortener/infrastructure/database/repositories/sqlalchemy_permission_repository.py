from typing import List, Optional
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

    def get_by_name(self, name: str) -> Optional[Permission]:
        """
        Retrieve a single permission by name.

        Args:
            name: Exact permission name.

        Returns:
            Permission entity if found, else ``None``.
        """
        model = self.session.query(PermissionModel).filter_by(name=name).first()
        
        return self._to_domain(model) if model else None

    def save(self, permission: Permission) -> Permission:
        """
        Insert or update a permission.

        Args:
            permission: Domain Permission entity.

        Returns:
            The same Permission entity (the ORM model is updated in place).
        """
        model = self.session.query(PermissionModel).filter_by(id=permission.id).first()
        
        if not model:
            model = PermissionModel(id=permission.id)
            self.session.add(model)
        
        self._update_model(model, permission)
        self.session.flush()
        
        return self._to_domain(model)

    def list_all(self) -> List[Permission]:
        """
        Return all permissions in the system.

        Returns:
            List of all Permission entities.
        """
        models = self.session.query(PermissionModel).all()
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

    def _update_model(self, model: PermissionModel, domain: Permission):
        """
        Copy fields from domain Permission to the ORM model in-place.

        Args:
            model: Existing PermissionModel instance.
            domain: Domain Permission with new values.
        """
        model.name = domain.name
        model.resource = domain.resource
        model.action = domain.action
        model.description = domain.description
