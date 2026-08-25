from datetime import datetime
from typing import List, Optional
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.orm import Session, selectinload

from link_shortener.infrastructure.database.models.associations import (
    user_role_table,
)
from link_shortener.infrastructure.database.models.permission_model import PermissionModel
from link_shortener.infrastructure.database.models.role_model import RoleModel
from link_shortener.infrastructure.database.models.base import Base
from link_shortener.infrastructure.database.models.user_model import UserModel
from link_shortener.application import Logger
from link_shortener.domain import (
    EmailAlreadyRegisteredError, Role, RoleNotFoundError, User,
    UserNotFoundError, UserRepository, Email, PasswordHash, Permission
)


EMAIL_INDEX_NAME = next(
    index.name
    for index in Base.metadata.tables[UserModel.__tablename__].indexes
    if [column.name for column in index.columns] == ["email"]
)
"""Name of the unique index on ``users.email``.

Read off the model rather than written out, because the name is what
PostgreSQL reports a violation of and the two would otherwise have to be
kept in step by hand. The migration creates it under this name as well,
and ``test_schema_matches_migration`` is what holds those together.
"""


def _is_email_clash(error: IntegrityError) -> bool:
    """
    Report whether an integrity error is the address index refusing.

    Asked because a single ``flush`` writes the account and its role
    associations, so "something violated a constraint" is not the same
    question as "that address is taken".

    The two databases say it differently, and both forms are measured:
    PostgreSQL 15 names the constraint --
    ``duplicate key value violates unique constraint "ix_users_email"``,
    reachable as ``diag.constraint_name`` -- while SQLite names the column
    in the message and offers no diagnostics: ``UNIQUE constraint failed:
    users.email``.

    Args:
        error: The integrity error the flush raised.

    Returns:
        ``True`` if the address index is what refused the write.
    """
    diagnostics = getattr(error.orig, "diag", None)
    constraint = getattr(diagnostics, "constraint_name", None)
    if constraint:
        return constraint == EMAIL_INDEX_NAME
    return "users.email" in str(error.orig)


def _role_that_went_away(error: IntegrityError, user: User) -> Optional[Role]:
    """
    Say which of the account's roles the write found already gone.

    The other way this ``flush`` can fail, and the mirror of
    ``_is_email_clash``: ``_sync_roles`` reads each role before writing
    the association, and that read goes stale the moment another
    transaction commits. Measured on the running stack -- ``PUT
    /api/v1/admin/users/<id>/roles`` naming a role, ``DELETE
    /api/v1/admin/roles/<name>`` two milliseconds later -- the assignment
    was answered **500** with ``ForeignKeyViolation: insert or update on
    table "user_roles" violates foreign key constraint``. That is the
    situation ``_sync_roles`` already raises ``RoleNotFoundError`` for,
    reached a moment later, so it is worth the same answer rather than a
    different one.

    Read off the diagnostics rather than off the constraint's name,
    because these foreign keys are declared without one and the name in
    the message is whatever the database chose to generate. What is
    asked instead is which table refused and which key it named, and the
    key is matched back to the roles this write was carrying -- so a
    violation from anywhere else answers ``None`` and is re-raised as it
    came.

    Args:
        error: The integrity error the flush raised.
        user: The account whose roles were being written.

    Returns:
        The role the association pointed at, or ``None`` if this is not
        that failure -- including on a database that reports no
        diagnostics at all, which is every engine but PostgreSQL here.
    """
    diagnostics = getattr(error.orig, "diag", None)
    if getattr(diagnostics, "table_name", None) != user_role_table.name:
        return None

    detail = getattr(diagnostics, "message_detail", None) or ""
    return next((role for role in user.roles if role.id in detail), None)


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

        Raises:
            EmailAlreadyRegisteredError: If the write collides with an
                address somebody else has just registered -- that index
                and no other constraint this flush can touch.
            RoleNotFoundError: If the user carries a role no row answers
                to, whether that was already so when the roles were read
                or became so before they were written.
            UserNotFoundError: If the account was deleted between this
                write's read and its flush.
        """
        model = self.session.get(UserModel, user.id)
        if not model:
            model = UserModel(id=user.id)
            self.session.add(model)
        self._domain_to_orm_fields(user, model)
        self._sync_roles(user, model)
        try:
            self.session.flush()
        except IntegrityError as clash:
            # The unique index on ``users.email`` is the only authority on
            # whether an address is free; every caller checks by reading
            # first, and that reading goes stale the moment another
            # transaction commits. Without this, simultaneous registrations
            # of one address answered 202 to the first and 500 to the rest
            # -- measured, five at once: 202, 500, 500 and two throttled --
            # so a public endpoint blamed the service for a request that
            # was merely late, and the difference in answers told a caller
            # what the 202 is worded to withhold.
            #
            # The same ``ValidationError`` the read-first check raises, so
            # both routes to the same fact carry one sentence and one
            # field. The session is unusable afterwards; the unit of work
            # rolls it back on the way out.
            #
            # Only that index, though. This ``flush`` also writes the role
            # associations ``_sync_roles`` just built, and every violation
            # they can raise arrived here as "Email already registered":
            # measured on the running stack, ``PUT
            # /api/v1/admin/users/<id>/roles`` naming one role twice was
            # answered `409 EMAIL_ALREADY_REGISTERED` for a request that
            # carries no address at all. Anything that is not the address
            # is re-raised as it came, because a wrong answer is worse
            # than an unhandled one: 500 says the service does not know,
            # and this said it knew something untrue.
            if not _is_email_clash(clash):
                vanished = _role_that_went_away(clash, user)
                if vanished is None:
                    raise
                raise RoleNotFoundError(vanished.name) from clash
            raise EmailAlreadyRegisteredError() from clash
        except StaleDataError as gone:
            # The account was there when this write read it and is not
            # there now: somebody deleted it in between. The same
            # arrangement ``delete`` was given for two simultaneous
            # deletions, on the other side of the same race -- measured
            # on the running stack, ``POST
            # /api/v1/admin/users/<id>/deactivate`` against a
            # simultaneous ``DELETE`` of that account answered **500**
            # twice in three attempts, with ``StaleDataError: UPDATE
            # statement on table 'users' expected to update 1 row(s); 0
            # were matched``.
            #
            # Every administrative write on an account comes through
            # here -- activation, suspension, confirmation, re-roling --
            # so the answer is given once here rather than four times
            # above, and it is the answer the account's absence already
            # has everywhere else: 404.
            raise UserNotFoundError(user.id) from gone
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
        """Paginated list of all users, in address order.

        The order is the port's requirement, and the reason it is one is
        written there. What is decided here is how it is met: by
        ``users.email``, which is unique and already carries an index, so
        the order is total without a tie-break and costs no index this
        schema does not have. Ordering by ``created_at`` -- which the link
        listing next door does -- would sort the table on every page,
        there being no index on it.

        A signed-in administrator is worth naming as the commonest way
        the unordered listing used to move: ``last_login`` is a write.

        Args:
            limit: Maximum number of users to return.
            offset: Number of users to skip.

        Returns:
            List of User entities, in address order.
        """
        models = (
            self.session.query(UserModel)
            .options(selectinload(UserModel.roles).selectinload(RoleModel.permissions))
            .order_by(UserModel.email.asc())
            .limit(limit)
            .offset(offset)
            .all()
        )
        return [self._orm_to_domain(m) for m in models]

    ADMINISTRATOR_SET_LOCK_NAMESPACE = -900370853
    """First half of the advisory lock key for the administrator set.

    Derived the way the guest quota's namespace is, so it can be
    re-derived and never drifts:
    ``blake2b(b"link_shortener.administrator_set", digest_size=4)`` read as
    a signed 32-bit integer.
    """

    ADMINISTRATOR_SET_LOCK_KEY = 0
    """Second half of the key.

    A constant rather than a value derived from anything: unlike the guest
    quota, which is per identifier, there is one administrator set and
    every change to it waits on every other. They are rare, and the wait
    is what makes the count mean something.
    """

    def lock_administrator_set(self) -> None:
        """Serialise every change to who holds ``admin:all``.

        Uses ``pg_advisory_xact_lock``, as the guest quota does and for the
        same reason: there is no row to lock. The thing being protected is
        a set -- "somebody, anybody, still has ``admin:all``" -- and two
        administrators demoting each other lock two different rows and
        never meet.

        On any other engine this does nothing, and the guard is advisory
        there. PostgreSQL is what production runs; SQLite serves local
        development and the test suite, whose writes are serialised anyway.
        """
        if self.session.get_bind().dialect.name != "postgresql":
            return

        self.session.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :key)"),
            {
                "namespace": self.ADMINISTRATOR_SET_LOCK_NAMESPACE,
                "key": self.ADMINISTRATOR_SET_LOCK_KEY,
            },
        )

    def count_active_with_permission(
        self,
        permission_name: str,
        excluding_user_id: Optional[str] = None,
        excluding_role_id: Optional[str] = None,
    ) -> int:
        """Count active users holding a permission through any role.

        Args:
            permission_name: Permission to look for (e.g. ``"admin:all"``).
            excluding_user_id: User to leave out of the count.
            excluding_role_id: Role to disregard while counting.

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
        if excluding_role_id is not None:
            # On the join, not on the user: somebody holding the permission
            # through a second role keeps counting, and only the path
            # through this one is disregarded.
            query = query.filter(RoleModel.id != excluding_role_id)
        # Distinct because a user holding the permission through two roles
        # is still one administrator.
        return query.distinct().count()

    def count_with_role(self, role_id: str) -> int:
        """Count the accounts wearing a role, active or not.

        Args:
            role_id: The role to count the wearers of.

        Returns:
            How many accounts hold it.
        """
        # No filter on ``is_active``: a suspended account wears the role
        # and loses it with the rest. Distinct for the reason
        # ``count_active_with_permission`` is: the join can repeat a row.
        return (
            self.session.query(UserModel.id)
            .join(UserModel.roles)
            .filter(RoleModel.id == role_id)
            .distinct()
            .count()
        )

    def delete(self, user_id: str) -> bool:
        """Permanently delete a user.

        Answers ``False`` for an account that is not there, and an account
        somebody else deleted a moment ago is not there either. The read
        above is a hint that goes stale the moment another transaction
        commits, exactly as the address lookup is in ``save``: measured on
        the running stack, two simultaneous ``DELETE
        /api/v1/admin/users/<id>`` answered 200 and **500**, because the
        second flushed a cascade whose rows the first had already taken --
        ``StaleDataError: DELETE statement on table 'user_roles' expected
        to delete 1 row(s); Only 0 were matched``. That is the service
        blaming itself for a request that was merely late, which is the
        arrangement `save` and ``SQLAlchemyRoleRepository.save`` were both
        given for their own races. The caller now gets ``False`` and the
        route answers 404, which is what the account's absence is.

        Flushed here rather than left to the commit, because that is where
        the error surfaces and there is nothing above this to turn it into
        an answer.

        Args:
            user_id: UUID string of the user.

        Returns:
            ``True`` if a user was deleted, ``False`` if it did not exist
            or had just been deleted by somebody else.
        """
        model = self.session.get(UserModel, user_id)
        if not model:
            return False

        self.session.delete(model)
        try:
            self.session.flush()
        except StaleDataError:
            # The session cannot be used further; the unit of work rolls
            # it back on the way out, which is what the losing side of
            # this race wants -- it has nothing left to write.
            return False
        return True

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

        Args:
            user: Domain User.
            model: UserModel ORM instance.

        Raises:
            RoleNotFoundError: If the user carries a role no row answers
                to. Saving a user is not how a role comes into existence:
                this method used to create the missing row itself, with
                ``is_system=False`` and no permissions at all, which is a
                write into the roles table from the user repository and a
                role stripped of everything the domain entity carried.
                Two administrators are enough to reach it -- one deletes a
                role between the other's lookup and save, and the role
                came back empty and unprotected, silently.

        Matched on the id rather than on the name for the same reason: a
        role deleted and made again under its old name is a different
        role, and the name would have bound the account to it.
        """
        model.roles = []
        for role in user.roles:
            role_model = self.session.get(RoleModel, role.id)
            if role_model is None:
                raise RoleNotFoundError(role.name)
            model.roles.append(role_model)
