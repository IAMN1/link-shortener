"""
Utility to load roles and permissions from a YAML configuration file.

Supports idempotent creation; can optionally update existing records.
"""

from pathlib import Path
from typing import Any, Dict
import uuid
import yaml
from sqlalchemy.orm import Session

from link_shortener.infrastructure.database.models.permission_model import PermissionModel
from link_shortener.infrastructure.database.models.role_model import RoleModel

class RoleLoader:
    """
    Reads a YAML file defining permissions and roles and persists them.

    Typical usage::

        loader = RoleLoader(session)
        loader.load_from_yaml(Path('rbac.yaml'), update_existing=False)
    """

    def __init__(self, session: Session):
        """
        Args:
            session: An active SQLAlchemy session.
        """
        self.session = session

    def load_from_yaml(self, file_path: Path, update_existing: bool = False) -> None:
        """
        Load and persist roles/permissions from a YAML file.

        Processing order:
        1. Permissions are created if missing; existing permissions are
           never modified unless ``update_existing`` is True.
        2. Roles are upserted. System roles (``is_system: true``) are
           skipped when ``update_existing=False``, otherwise they are
           updated as well.

        Args:
            file_path: Path to the YAML file.
            update_existing: If True, update existing records; otherwise
                only create missing records.
        """
        with open(file_path, "r") as f:
            config = yaml.safe_load(f)

        # 1. Upsert permissions
        for perm_def in config.get("permissions", []):
            self._upsert_permission(perm_def, update_existing=False)

        # 2. Upsert roles (skip system roles if not updating existing)
        for role_def in config.get("roles", []):
            if role_def.get("is_system", False) and not update_existing:
                continue
            self._upsert_role(role_def, update_existing=True)

    def _upsert_permission(
        self, perm_def: Dict[str, Any], update_existing: bool = False
    ) -> PermissionModel:
        """
        Insert a new permission or, if allowed, update an existing one.

        Args:
            perm_def: Dictionary with keys matching PermissionModel fields.
            update_existing: Whether to update an existing record.

        Returns:
            The persistent PermissionModel instance.
        """
        perm = self.session.query(PermissionModel).filter_by(
            name=perm_def["name"]
        ).first()
        if perm:
            if update_existing:
                for key, value in perm_def.items():
                    setattr(perm, key, value)
        else:
            perm = PermissionModel(id=str(uuid.uuid4()), **perm_def)
            self.session.add(perm)
        return perm

    def _upsert_role(
        self, role_def: Dict[str, Any], update_existing: bool = True
    ) -> RoleModel:
        """
        Insert or update a role and its permission associations.

        The ``permissions`` list inside the dict is consumed to set the
        many-to-many relationship.

        Args:
            role_def: Dictionary describing the role (must contain a
                ``permissions`` key with a list of permission names).
            update_existing: If True, an existing role's fields and
                associations are replaced.

        Returns:
            The persistent RoleModel instance.
        """
        role_name = role_def["name"]
        perm_names = role_def.pop("permissions", [])

        role = self.session.query(RoleModel).filter_by(name=role_name).first()
        if role:
            if not update_existing:
                return role
            # Update scalar fields
            for key, value in role_def.items():
                setattr(role, key, value)
        else:
            role = RoleModel(id=str(uuid.uuid4()), **role_def)
            self.session.add(role)

        # Replace permission associations
        perms = self.session.query(PermissionModel).filter(
            PermissionModel.name.in_(perm_names)
        ).all()
        role.permissions = perms

        return role
