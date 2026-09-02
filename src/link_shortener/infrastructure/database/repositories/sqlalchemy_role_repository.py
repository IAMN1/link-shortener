from typing import List, Optional
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from link_shortener.infrastructure.database.models.associations import (
    role_permission_table,
)
from link_shortener.infrastructure.database.models.permission_model import PermissionModel
from link_shortener.infrastructure.database.models.role_model import RoleModel
from link_shortener.domain import (
    Permission, Role, RoleAlreadyExistsError, RoleNotFoundError, RoleRepository
)


def _is_name_clash(error: IntegrityError) -> bool:
    """
    Report whether an integrity error is the name constraint refusing.

    Asked because a single ``flush`` writes the role and its permission
    associations, so "something violated a constraint" is not the same
    question as "that name is taken" -- the distinction
    ``SQLAlchemyUserRepository`` draws for the address, made here for the
    same reason and after the same measurement.

    The two databases say it differently, and both forms are measured:
    PostgreSQL 15 names the table in its diagnostics -- ``table_name`` is
    ``roles``, with ``roles_name_key`` as the constraint -- while SQLite
    names the column in the message and offers no diagnostics at all:
    ``UNIQUE constraint failed: roles.name``. The table rather than the
    constraint, because this uniqueness is declared on the column and the
    name in the message is whatever the database generated for it.

    Args:
        error: The integrity error the flush raised.

    Returns:
        ``True`` if the name is what refused the write.
    """
    diagnostics = getattr(error.orig, "diag", None)
    table = getattr(diagnostics, "table_name", None)
    if table is not None:
        return table == RoleModel.__tablename__
    return "roles.name" in str(error.orig)


def _role_is_already_gone(error: IntegrityError, role: Role) -> bool:
    """
    Report whether the write found the role itself deleted under it.

    The other way this ``flush`` can fail: the associations it writes
    point at a role somebody deleted a moment ago. Measured on the
    running stack -- ``PUT /api/v1/admin/roles/<name>/permissions``
    against a ``DELETE`` of that role a couple of milliseconds later --
    and answered ``409 ROLE_ALREADY_EXISTS`` for a request that asked to
    take no name at all, the broad catch below having read every
    violation as the name.

    Args:
        error: The integrity error the flush raised.
        role: The role being written.

    Returns:
        ``True`` if an association could not find this role to point at.
    """
    diagnostics = getattr(error.orig, "diag", None)
    if getattr(diagnostics, "table_name", None) != role_permission_table.name:
        return False

    detail = getattr(diagnostics, "message_detail", None) or ""
    return role.id in detail


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

        Raises:
            RoleAlreadyExistsError: If the write collides with a name
                somebody else has just taken -- that constraint and no
                other this flush can touch.
            RoleNotFoundError: If the role was deleted between this
                write's read and its flush.
        """

        model = self.session.query(RoleModel).filter_by(id=role.id).first()
        if not model:
            model = RoleModel(id=role.id)
            self.session.add(model)
        self._update_model(model, role)
        try:
            self.session.flush()
        except IntegrityError as clash:
            # The unique index on ``roles.name`` is the only authority on
            # whether a name is free; the lookup ``create_role`` does
            # first is a hint that goes stale the moment another
            # transaction commits. Without this, simultaneous creations
            # of one name answered 201 to the first and 500 to the rest
            # -- measured, six at once: 201, 409, 409, 500, 500, 500 --
            # so one situation had two codes and the service blamed
            # itself for a request that was simply late. The same
            # arrangement ``SQLAlchemyLinkRepository`` makes for
            # ``short_code``.
            #
            # The session is unusable afterwards; the unit of work rolls
            # it back on the way out.
            #
            # Only that constraint, though. This ``flush`` also writes the
            # permission associations ``_update_model`` just built, and
            # every violation they can raise arrived here as "that name is
            # taken" -- the same defect the address catch next door was
            # narrowed for, and recorded in `docs/decisions.md` as a mine
            # nothing could reach. A race reaches it: measured, ``PUT
            # /admin/roles/<name>/permissions`` against a simultaneous
            # ``DELETE`` of that role answered `409 ROLE_ALREADY_EXISTS`
            # for a request that asks to take no name at all.
            if _is_name_clash(clash):
                raise RoleAlreadyExistsError(role.name) from clash
            if _role_is_already_gone(clash, role):
                raise RoleNotFoundError(role.name) from clash
            raise
        except StaleDataError as gone:
            # The role was there when this write read it and is not there
            # now. The same answer `delete` below gives for the other
            # side of this race, and for the same reason: 500 would be
            # the service blaming itself for a request that was late.
            raise RoleNotFoundError(role.name) from gone
        return self._to_domain(model)

    def delete(self, role_id: str) -> None:
        """
        Permanently delete a role.

        The read above is a hint that goes stale the moment another
        transaction commits, exactly as the name lookup is in ``save``:
        measured on the running stack, ``PUT
        /api/v1/admin/roles/<name>/permissions`` and a ``DELETE`` of that
        role two milliseconds later answered 200 and **500**, with
        ``StaleDataError: DELETE statement on table 'role_permissions'
        expected to delete 1 row(s); Only 0 were matched`` -- the
        deletion flushed a cascade whose rows the permission change had
        already replaced. The service blamed itself for a request that
        was merely late, which is the arrangement ``save`` here,
        ``SQLAlchemyUserRepository.save`` and ``.delete`` were all given
        for their own races.

        Raised as the role's absence rather than returned as one: this
        port answers ``None``, and the service above raises
        ``RoleNotFoundError`` for a name it could not read, so the losing
        side of the race is answered 404 by the same sentence as a name
        that was never there.

        Args:
            role_id: UUID string of the role to delete.

        Raises:
            RoleNotFoundError: If the role was deleted, or its
                permissions replaced, between this read and this flush.
        """
        model = self.session.query(RoleModel).filter_by(id=role_id).first()
        if model:
            name = model.name
            self.session.delete(model)
            try:
                self.session.flush()
            except StaleDataError as gone:
                # The session cannot be used further; the unit of work
                # rolls it back on the way out, which is what the losing
                # side of this race wants -- it has nothing left to write.
                raise RoleNotFoundError(name) from gone

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
            permissions=tuple(perms)
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
