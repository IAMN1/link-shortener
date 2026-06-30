from typing import List, Optional
from sqlalchemy.orm import Session

from link_shortener.infrastructure.database.models.permission_model import PermissionModel
from link_shortener.infrastructure.database.models.role_model import RoleModel
from link_shortener.domain import Role, RoleRepository, Permission


class SQLAlchemyRoleRepository(RoleRepository):
    """
    Concrete repository for Role entities.

    Manages the many-to-many association with PermissionModel when saving.
    """
    
    def __init__(self, session: Session):
        """
        Args:
            session: Active SQLAlchemy session.
        """
        self.session = session
    
    def get_by_name(self, name: str) -> Optional[Role]:
        """
        Look up a role by its unique name.

        Args:
            name: Role name (e.g., ``"admin"``).

        Returns:
            Role entity if found, else ``None``.
        """
        model= self.session.query(RoleModel).filter_by(name=name).first()
        return self._to_domain(model) if model else None
    
    def save(self, role: Role) -> Role:
        """
        Insert or update a role.

        If a role with the same ID already exists, its fields and
        permission associations are updated.

        Args:
            role: Domain Role entity.

        Returns:
            The updated domain Role (re-hydrated from the ORM).
        """

        model = self.session.query(RoleModel).filter_by(id=role.id).first()
        if not model:
            model = RoleModel(id=role.id)
            self.session.add(model)
        self._update_model(model, role)
        self.session.flush()
        return self._to_domain(model)

    def delete(self, role_id: str) -> None:
        """
        Permanently delete a role.

        Args:
            role_id: UUID string of the role to delete.
        """
        model = self.session.query(RoleModel).filter_by(id=role_id).first()
        if model:
            self.session.delete(model)
            self.session.flush()

    def list_all(self) -> List[Role]:
        """
        Retrieve all roles.

        Returns:
            List of all Role entities (with their permissions eagerly loaded).
        """
        models = self.session.query(RoleModel).all()
        return [self._to_domain(m) for m in models]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------
    def _to_domain(self, model: RoleModel) -> Role:
        """
        Convert an ORM RoleModel to a domain Role.

        Also converts the associated permissions.

        Args:
            model: RoleModel instance.

        Returns:
            Domain Role entity.
        """
        perms = [
            Permission(
                id=p.id,
                name=p.name,
                resource=p.resource,
                action=p.action,
                description=p.description
            )
            for p in model.permissions
        ]
        return Role(
            id=model.id,
            name=model.name,
            description=model.description,
            is_system=model.is_system,
            permissions=perms
        )

    def _update_model(self, model: RoleModel, domain: Role):
        """
        Copy scalar fields and replace the permission collection.

        Args:
            model: Existing RoleModel ORM instance.
            domain: Domain Role with the desired values.
        """
        model.name = domain.name
        model.description = domain.description
        model.is_system = domain.is_system

        # Load the desired PermissionModel instances and replace the collection
        permission_names = [p.name for p in domain.permissions]
        new_permissions = self.session.query(PermissionModel).filter(
            PermissionModel.name.in_(permission_names)
        ).all()
        # Replace the permission collection.
        model.permissions = new_permissions
