"""
Utility to load roles and permissions from a YAML configuration file.

Supports idempotent creation; can optionally update existing records.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any, Dict, List
import uuid
import yaml
from sqlalchemy.orm import Session

from link_shortener.domain.policies.role_policy import (
    require_valid_role_description, require_valid_role_name
)
from link_shortener.infrastructure.database.models.permission_model import PermissionModel
from link_shortener.infrastructure.database.models.role_model import RoleModel


@dataclass
class RegrantedRole:
    """
    A role whose permissions this pass replaced, and what it replaced.

    Carried out of the loader because the caller has to record it: a
    change to what a role grants moves every account wearing it at once,
    which is the widest-reaching act the audit vocabulary has a name for.
    ``--update-existing`` performs it, and the journal could not see it --
    the summary said what had been created and what had been left alone,
    and nothing about what had been rewritten.

    Attributes:
        name: The role.
        permissions_before: What it granted when the pass found it.
        permissions_after: What it grants now.
    """

    name: str
    permissions_before: List[str]
    permissions_after: List[str]


@dataclass
class LoadSummary:
    """
    What one seeding pass did, so the operator is not left guessing.

    Seeding leaves existing roles alone, which is the intent -- and it means
    a role edited through the admin API keeps that edit, while the YAML the
    operator just changed has no effect on it. Silence looked identical in
    both cases.

    Attributes:
        permissions_created: Names of permissions inserted.
        roles_created: Names of roles inserted.
        roles_left_alone: Names of roles that already existed and were not
            touched, neither their fields nor their permissions.
        roles_reprotected: Names of roles that existed but had lost their
            system flag, and had it restored.
        roles_regranted: Roles whose permissions this pass replaced, with
            what they granted before and after. Only where the set
            actually changed: running the same file twice rewrites the
            same associations, and a record of that says something
            happened when nothing did.
    """

    permissions_created: List[str] = field(default_factory=list)
    roles_created: List[str] = field(default_factory=list)
    roles_left_alone: List[str] = field(default_factory=list)
    roles_reprotected: List[str] = field(default_factory=list)
    roles_regranted: List[RegrantedRole] = field(default_factory=list)

    def describe(self) -> str:
        """
        Render a one-line report.

        Returns:
            Human-readable summary of the pass.
        """
        parts = [
            f"permissions created: {len(self.permissions_created)}",
            f"roles created: {len(self.roles_created)}",
        ]
        if self.roles_reprotected:
            parts.append(
                "system flag restored: "
                + ", ".join(sorted(self.roles_reprotected))
            )
        if self.roles_left_alone:
            parts.append(
                "left as they are: " + ", ".join(sorted(self.roles_left_alone))
            )
        return "; ".join(parts)


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

    def load_from_yaml(
        self, file_path: Path, update_existing: bool = False
    ) -> LoadSummary:
        """
        Load and persist roles/permissions from a YAML file.

        Processing order:
        1. Permissions are created if missing; existing permissions are
           never modified unless ``update_existing`` is True.
        2. Roles are created if missing. An existing role is left entirely
           alone unless ``update_existing`` is True -- its fields and its
           permissions both.

        Args:
            file_path: Path to the YAML file.
            update_existing: If True, update existing records; otherwise
                only create missing records.

        Returns:
            What the pass did, including which roles it deliberately did
            not touch.
        """
        with open(file_path, "r") as f:
            config = yaml.safe_load(f)

        summary = LoadSummary()

        # 1. Upsert permissions. The flag is passed down rather than
        # hard-coded False, which is what it was: ``--update-existing``
        # said "Update existing roles and permissions" and this docstring
        # promised the same, while an edited description or resource in
        # the file changed nothing and the command still reported
        # "Updated roles and permission from <file>".
        for perm_def in config.get("permissions", []):
            self._upsert_permission(
                perm_def, update_existing=update_existing, summary=summary
            )

        # Push the new permissions to the database before the roles look them
        # up. Sessions are built with autoflush=False, so without this the
        # query in _upsert_role sees none of them and every role is linked to
        # an empty permission set -- on a fresh database that leaves even
        # admin with no rights until a second seeding pass.
        self.session.flush()

        # 2. Upsert roles.
        for role_def in config.get("roles", []):
            self._upsert_role(
                role_def, update_existing=update_existing, summary=summary
            )

        return summary

    def _upsert_permission(
        self,
        perm_def: Dict[str, Any],
        update_existing: bool = False,
        summary: Optional[LoadSummary] = None,
    ) -> PermissionModel:
        """
        Insert a new permission or, if allowed, update an existing one.

        Args:
            perm_def: Dictionary with keys matching PermissionModel fields.
            update_existing: Whether to update an existing record.
            summary: Record of what the pass did, appended to when given.

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
            if summary is not None:
                summary.permissions_created.append(perm_def["name"])
        return perm

    def _upsert_role(
        self,
        role_def: Dict[str, Any],
        update_existing: bool = True,
        summary: Optional[LoadSummary] = None,
    ) -> RoleModel:
        """
        Insert a role, or update one when updating is allowed.

        The ``permissions`` list inside the dict is consumed to set the
        many-to-many relationship.

        An existing role is left alone in full when ``update_existing`` is
        False -- which is how every caller but the explicit
        ``--update-existing`` CLI flag calls it. Reassigning the permission
        associations regardless would take back a permission granted to a
        system role through the admin API at the next seeding, which in
        ``development`` is every application start.

        Args:
            role_def: Dictionary describing the role (must contain a
                ``permissions`` key with a list of permission names).
            update_existing: If True, an existing role's fields and
                associations are replaced.
            summary: Record of what the pass did, appended to when given.

        Returns:
            The persistent RoleModel instance.

        Raises:
            ValidationError: If the file names a role something a role may
                not be called, or describes it at a length the column
                cannot hold.
        """
        role_name = role_def["name"]
        # The other door the admin API's schema does not stand at. A name
        # with a slash in it makes a role no route can address: created
        # here, it could then be removed by nothing short of SQL.
        require_valid_role_name(role_name)
        # And the width of what the column holds, which the schema states
        # for the API's door and nothing stated for this one: measured, a
        # 256-character description here came back as a driver traceback
        # rather than as a sentence naming the field.
        require_valid_role_description(role_def.get("description"))
        perm_names = role_def.pop("permissions", [])

        role = self.session.query(RoleModel).filter_by(name=role_name).first()
        existed = role is not None
        # Narrowed on the row itself rather than on the flag beside it: the
        # flag says the same thing, but only the row tells a reader -- and a
        # checker -- that the branch below cannot see None.
        if role is not None:
            if update_existing:
                # Update scalar fields
                for key, value in role_def.items():
                    setattr(role, key, value)
            else:
                # One field is restored even here: whether the role is a
                # system role. It is not a setting an operator tunes but a
                # statement that this role is part of the service, and it
                # carries the protection against deletion and against being
                # edited through the admin API. ``create_role`` writes
                # ``is_system=False`` unconditionally, so a system role
                # deleted and made again through the API came back
                # unprotected -- and nothing could ever mark it back, since
                # seeding did not touch the fields of an existing role.
                if role_def.get("is_system") and not role.is_system:
                    role.is_system = True
                    if summary is not None:
                        summary.roles_reprotected.append(role_name)
                elif summary is not None:
                    summary.roles_left_alone.append(role_name)
        else:
            role = RoleModel(id=str(uuid.uuid4()), **role_def)
            self.session.add(role)
            if summary is not None:
                summary.roles_created.append(role_name)

        if not existed or update_existing:
            # What it granted before the replacement, read while it is
            # still there. The caller records the change, and a record
            # that cannot say what was taken away answers half of what an
            # investigator asks.
            granted_before = sorted(p.name for p in role.permissions)

            # Replace permission associations
            perms = self.session.query(PermissionModel).filter(
                PermissionModel.name.in_(perm_names)
            ).all()
            role.permissions = perms

            granted_after = sorted(p.name for p in perms)
            # Only a real change, and only for a role that already
            # existed: a role created a moment ago is reported as created,
            # and reporting it as regranted as well would put two records
            # against one act.
            if existed and granted_before != granted_after and summary is not None:
                summary.roles_regranted.append(
                    RegrantedRole(
                        name=role_name,
                        permissions_before=granted_before,
                        permissions_after=granted_after,
                    )
                )

        return role
