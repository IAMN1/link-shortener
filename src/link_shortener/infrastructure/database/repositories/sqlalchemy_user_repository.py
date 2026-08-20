from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import Session, selectinload

from link_shortener.infrastructure.database.models.permission_model import PermissionModel
from link_shortener.infrastructure.database.models.role_model import RoleModel
from link_shortener.infrastructure.database.models.user_model import UserModel
from link_shortener.application import Logger
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

    def __init__(self, session: Session, logger: Optional[Logger] = None):
        """
        Args:
            session: Active SQLAlchemy session.
            logger: Where to report a stored address that normalisation
                would change. Optional because a repository built by hand
                -- a test, a script -- has nobody to report to; the
                application always supplies one through the unit of work.
        """
        self.session = session
        self.logger = logger

    def _report_a_row_that_predates_normalisation(self, stored: str) -> None:
        """
        Report a stored address that is not in the normalised form.

        Such a row is invisible to every lookup -- addresses are compared
        exactly -- so its owner cannot sign in, and registering the same
        mailbox again makes a second account for it. Reported rather than
        rewritten here: the remedy is ``flask maintenance
        normalize-emails``, which can see a collision this cannot.

        Repeated on every save deliberately: the row outlives the
        request, and a message that appeared once would be gone from the
        log by the time anyone looked.

        Args:
            stored: The address exactly as the database holds it.
        """
        if self.logger is None:
            return

        self.logger.warning(
            "Stored address is not in the normalised form, so no lookup "
            "will find it",
            stored_email=stored,
            normalised=Email.normalise(stored),
            remedy="flask maintenance normalize-emails",
        )

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

    def record_login(self, user_id: str, when: datetime) -> bool:
        """Note that an account has just signed in.

        A conditional update naming one column, rather than ``save`` on an
        entity read before the password was checked. That read and this
        write are separated by a bcrypt comparison, and ``save`` writes
        every column back: an account deactivated in that window came back
        active, and a password changed in it was replaced by the old hash.

        Args:
            user_id: The account that signed in.
            when: Time of the sign-in.

        Returns:
            True if a row was updated.
        """
        updated = (
            self.session.query(UserModel)
            .filter(UserModel.id == user_id)
            .update({UserModel.last_login: when}, synchronize_session=False)
        )
        self.session.flush()
        return updated == 1

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
            email=Email.from_storage(model.email),
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
        # Written back exactly as the entity holds it. Lowering happens
        # where an address is typed, and ``from_storage`` rebuilds a row
        # without repeating it, so a row written before that rule keeps
        # its own spelling instead of being quietly rewritten by whichever
        # request touched the account first -- and instead of colliding
        # with an account that already holds the lower-case form, which
        # reached the caller as a 500 on confirmation.
        model.email = user.email.value
        if model.email != Email.normalise(model.email):
            self._report_a_row_that_predates_normalisation(model.email)
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
