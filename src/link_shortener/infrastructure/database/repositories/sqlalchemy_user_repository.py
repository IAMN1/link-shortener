from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import Session, selectinload

from link_shortener.infrastructure.database.models.permission_model import PermissionModel
from link_shortener.infrastructure.database.models.role_model import RoleModel
from link_shortener.infrastructure.database.models.user_model import UserModel
from link_shortener.domain import (
    Role, User, UserRepository,
    Email, PasswordHash, Permission
)


class SQLAlchemyUserRepository(UserRepository):
    """
    Concrete repository for User entities using SQLAlchemy.

    Always eagerly loads the roles and their permissions to construct
    a fully populated domain User.
    """

    def __init__(self, session: Session):
        """
        Args:
            session: Active SQLAlchemy session.
        """
        self.session = session

    def save(self, user: User) -> User:
        """Insert or update a user.

        If a user with the same ID already exists, its fields and role
        associations are updated.

        Args:
            user: Domain User entity.

        Returns:
            The same user instance (the session is flushed but the entity
            is not re-hydrated from the ORM).
        """
        model = self.session.get(UserModel, user.id)
        if not model:
            model = UserModel(id=user.id)
            self.session.add(model)
        self._domain_to_orm_fields(user, model)
        self._sync_roles(user, model)
        self.session.flush()
        return user

    def find_by_email(self, email: Email) -> Optional[User]:
        """Look up a user by email.

        Args:
            email: Email value object.

        Returns:
            User entity if found, else ``None``.
        """
        model = (
            self.session.query(UserModel)
            .options(selectinload(UserModel.roles).selectinload(RoleModel.permissions))
            .filter(UserModel.email == email.value)
            .first()
        )
        return self._orm_to_domain(model) if model else None

    def find_by_id(self, user_id: str) -> Optional[User]:
        """Look up a user by their ID.

        Args:
            user_id: UUID string.

        Returns:
            User entity if found, else ``None``.
        """
        model = (
            self.session.query(UserModel)
            .options(selectinload(UserModel.roles).selectinload(RoleModel.permissions))
            .filter(UserModel.id == user_id)
            .first()
        )
        return self._orm_to_domain(model) if model else None

    def list_all(self, limit: int = 100, offset: int = 0) -> List[User]:
        """Paginated list of all users.

        Args:
            limit: Maximum number of users to return.
            offset: Number of users to skip.

        Returns:
            List of User entities.
        """
        models = (
            self.session.query(UserModel)
            .options(selectinload(UserModel.roles).selectinload(RoleModel.permissions))
            .limit(limit)
            .offset(offset)
            .all()
        )
        return [self._orm_to_domain(m) for m in models]

    def count_active_with_permission(
        self, permission_name: str, excluding_user_id: Optional[str] = None
    ) -> int:
        """Count active users holding a permission through any role.

        Args:
            permission_name: Permission to look for (e.g. ``"admin:all"``).
            excluding_user_id: User to leave out of the count.

        Returns:
            Number of matching active users.
        """
        query = (
            self.session.query(UserModel.id)
            .join(UserModel.roles)
            .join(RoleModel.permissions)
            .filter(PermissionModel.name == permission_name)
            .filter(UserModel.is_active.is_(True))
        )
        if excluding_user_id is not None:
            query = query.filter(UserModel.id != excluding_user_id)
        # Distinct because a user holding the permission through two roles
        # is still one administrator.
        return query.distinct().count()

    def delete(self, user_id: str) -> bool:
        """Permanently delete a user.

        Args:
            user_id: UUID string of the user.

        Returns:
            ``True`` if a user was deleted, ``False`` if it did not exist.
        """
        model = self.session.get(UserModel, user_id)
        if model:
            self.session.delete(model)
            return True
        return False

    def delete_unverified_before(self, cutoff: datetime) -> int:
        """Delete accounts that were never confirmed and have run out of time.

        A bulk statement, which normally would not do for users: rows that
        vanish behind the application leave their links' cache entries
        behind, answering for links that no longer exist until the entries
        expire. It does here because these accounts never signed in --
        confirmation is what login requires -- so they own nothing that
        could be cached. Should that ever stop being true, this has to go
        back through ``DeleteUserUseCase``.

        The rows hanging off the account -- roles, sessions, confirmations
        -- go with it through ``ON DELETE CASCADE``, which SQLite honours
        only because the manager turns the pragma on for every connection.

        Args:
            cutoff: Registrations older than this are removed.

        Returns:
            Number of accounts deleted.
        """
        deleted = (
            self.session.query(UserModel)
            .filter(
                UserModel.email_verified.is_(False),
                UserModel.created_at < cutoff,
            )
            .delete(synchronize_session=False)
        )
        self.session.flush()
        return deleted

    # ------------------------------------------------------------------
    # Private conversion helpers
    # ------------------------------------------------------------------
    def _orm_to_domain(self, model: UserModel) -> User:
        """Fully reconstruct a User domain entity from the ORM model.

        Eagerly loads roles and permissions to build the complete aggregate.

        Args:
            model: UserModel ORM instance.

        Returns:
            Domain User.
        """
        roles = []
        for role_model in model.roles:
            perms = [
                Permission(
                    id=p.id,
                    name=p.name,
                    resource=p.resource,
                    action=p.action,
                    description=p.description,
                )
                for p in role_model.permissions
            ]
            role = Role(
                id=role_model.id,
                name=role_model.name,
                description=role_model.description,
                is_system=role_model.is_system,
                permissions=tuple(perms),
            )
            roles.append(role)
        return User(
            id=model.id,
            email=Email(model.email),
            password_hash=PasswordHash(model.password_hash),
            roles=roles,
            is_active=model.is_active,
            email_verified=model.email_verified,
            created_at=model.created_at,
            last_login=model.last_login,
        )

    def _domain_to_orm_fields(self, user: User, model: UserModel) -> UserModel:
        """Copy scalar fields from domain User to the ORM model.

        Role associations are handled separately.

        Args:
            user: Domain User.
            model: Existing or new UserModel instance.

        Returns:
            The same model instance (mutated).
        """
        model.email = user.email.value
        model.password_hash = user.password_hash.value
        model.is_active = user.is_active
        model.email_verified = user.email_verified
        model.created_at = user.created_at
        model.last_login = user.last_login
        return model

    def _sync_roles(self, user: User, model: UserModel):
        """Replace the ORM model's role collection with associations from the domain user.

        If a role referenced by the domain user does not yet exist in the database,
        a new RoleModel is created.

        Args:
            user: Domain User.
            model: UserModel ORM instance.
        """
        model.roles = []
        for role in user.roles:
            role_model = self.session.query(RoleModel).filter_by(name=role.name).first()
            if not role_model:
                # Create a stub role if it does not exist (roles are usually seeded)
                role_model = RoleModel(id=role.id, name=role.name)
                self.session.add(role_model)
            model.roles.append(role_model)
