from typing import List, Optional
import uuid

from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.domain import (
    PermissionsNotFoundError, Role, RoleAlreadyExistsError, RoleNotFoundError
)
from link_shortener.domain.policies.role_policy import (
    require_valid_role_description, require_valid_role_name
)


class RoleManagementService:
    """
    Service for managing roles (used by admin use cases).

    Encapsulates creation, permission updates, and deletion of roles,
    ensuring system roles are protected.
    """

    @staticmethod
    def _refuse_unknown_permissions(requested: List[str], found) -> None:
        """
        Refuse a permission name the system does not know.

        Args:
            requested: Permission names as the caller wrote them.
            found: Permission entities the repository returned for them.

        Comparison is by name rather than by count, so a name repeated in
        the request is not mistaken for an unknown one.

        Raises:
            PermissionsNotFoundError: If any requested name has no
                permission behind it.
        """
        missing = set(requested) - {permission.name for permission in found}
        if missing:
            raise PermissionsNotFoundError(missing)

    @classmethod
    def resolve_permissions(cls, uow: UnitOfWork, permission_names: List[str]):
        """
        Turn permission names into the permissions they name.

        The counterpart of ``resolve_roles``, and the one door for it.

        Args:
            uow: Active unit of work.
            permission_names: Names as the caller wrote them.

        Returns:
            The permission entities, without duplicates.

        Raises:
            PermissionsNotFoundError: If any name has no permission
                behind it, naming all of them at once -- a request may
                carry a dozen, and bisecting a dozen is the cost this
                avoids.
        """
        permissions = uow.permissions.get_by_names(permission_names)
        cls._refuse_unknown_permissions(permission_names, permissions)
        return permissions

    @staticmethod
    def resolve_roles(uow: UnitOfWork, role_names: List[str]) -> List[Role]:
        """
        Turn role names into the roles they name.

        The one door for it. Four callers used to open it themselves --
        two admin use cases and two CLI commands -- and the two in the
        application layer raised ``VALIDATION_ERROR`` for a name nothing
        carries, which the status table answers 400. The role endpoints
        beside them answered 404 to that very question, so one situation
        had two codes, two statuses, and two msgids in the catalogue that
        a translator had to keep in step by hand.

        A name repeated in the request yields one role, the way
        ``resolve_permissions`` yields one permission for a name repeated
        there: what a request carries is the set an account is to wear,
        and naming a role twice does not name two roles. Without this the
        repeated role reached the association table as two identical rows
        and the primary key refused them -- measured on the running stack,
        ``{"roles": ["user", "user"]}`` was answered `409
        EMAIL_ALREADY_REGISTERED`, because that flush writes the
        associations too and every violation in it was read as the address
        index. That reading is narrowed now, but the request is a
        reasonable one and should simply work.

        Args:
            uow: Active unit of work.
            role_names: Names as the caller wrote them, in their order.

        Returns:
            The roles, in the order they were asked for, without repeats.

        Raises:
            RoleNotFoundError: At the first name nothing carries. The
                first rather than all of them, unlike
                ``PermissionsNotFoundError``: a request names a handful of
                roles and dozens of permissions, so bisection is not the
                cost there that it is for permissions.
        """
        roles = []
        seen = set()
        for name in role_names:
            role = uow.roles.get_by_name(name)
            if not role:
                raise RoleNotFoundError(name)
            # Deduplicated by identity rather than by the name asked for:
            # a role deleted and made again under its old name is a
            # different role, which is the same reason ``_sync_roles``
            # matches on the id.
            if role.id in seen:
                continue
            seen.add(role.id)
            roles.append(role)
        return roles

    def create_role(self,
                    uow: UnitOfWork,
                    name: str,
                    description: Optional[str],
                    permission_names: List[str]
    ) -> Role:
        """
        Create a new non-system role with specified permissions.

        Args:
            uow: Active unit of work.
            name: Unique role name.
            description: Human-readable description, or ``None``: the entity
                stores it as optional and the admin API sends it that way.
            permission_names: List of permission names to assign.

        Returns:
            The newly created Role entity.

        Raises:
            ValidationError: If the name is not one a role may be called,
                or the description is wider than the column holding it.
            RoleAlreadyExistsError: If the name is already taken.
            PermissionsNotFoundError: If any permission is missing.
        """
        # Asked here rather than trusted from the schema: the schema is one
        # of two doors, and the other is a YAML file read by
        # ``flask db load-custom-roles``.
        require_valid_role_name(name)
        # The same reasoning, and the half that was left out of it: a
        # description past the column's width reached PostgreSQL as a
        # ``StringDataRightTruncation``, which a caller meets as a 500.
        require_valid_role_description(description)

        existing = uow.roles.get_by_name(name)
        if existing:
            raise RoleAlreadyExistsError(name)
        permissions = self.resolve_permissions(uow, permission_names)

        role = Role(
            id=str(uuid.uuid4()),
            name=name,
            description=description,
            is_system=False,
            permissions=tuple(permissions)
        )
        return uow.roles.save(role)

    def update_role_permissions(self, uow: UnitOfWork, role_name: str, permission_names: List[str]) -> Role:
        """
        Replace the permissions of an existing role.

        Args:
            uow: Active unit of work.
            role_name: Role to update.
            permission_names: New list of permission names.

        Returns:
            Updated Role entity.

        Raises:
            RoleNotFoundError: If there is no role under that name.
            RoleIsSystemError: If the role is one the service owns.
            PermissionsNotFoundError: If any requested permission does not
                exist.
        """
        role = uow.roles.get_by_name(role_name)
        if not role:
            raise RoleNotFoundError(role_name)
        role.ensure_may_be_changed()

        permissions = self.resolve_permissions(uow, permission_names)

        updated_role = Role(
            id=role.id,
            name=role.name,
            description=role.description,
            is_system=role.is_system,
            permissions=tuple(permissions)
        )
        return uow.roles.save(updated_role)

    def delete_role(self, uow: UnitOfWork, role_name: str) -> None:
        """
        Delete a non-system role.

        Args:
            uow: Active unit of work.
            role_name: Name of the role to delete.

        Raises:
            RoleNotFoundError: If there is no role under that name.
            RoleIsSystemError: If the role exists but may not be deleted.
        """
        # Two different answers, and they were one exception: "no such
        # role" and "that role is protected" both came back as ValueError,
        # so the endpoint answered 400 to a name that simply is not there
        # -- while the user endpoint next to it answered 404 for exactly
        # the same question. They are two domain errors now, which is what
        # carries the distinction past the use case without a translation
        # from one exception vocabulary into another.
        role = uow.roles.get_by_name(role_name)
        if not role:
            raise RoleNotFoundError(role_name)
        role.ensure_may_be_changed()
        uow.roles.delete(role.id)
