"""
SQLAlchemy implementation of the Unit of Work pattern.

Manages a single database session and provides access to all repositories.
Supports read-only transactions (on PostgreSQL sets the transaction to READ ONLY).
"""

from types import TracebackType
from typing import Optional, Type
from sqlalchemy import text
from sqlalchemy.orm import Session

from link_shortener.application import Logger, UnitOfWork
from link_shortener.domain import (
    EmailVerificationRepository, LinkRepository, LinkVisitRepository,
    PasswordResetRepository, PermissionRepository,
    RefreshSessionRepository, RoleRepository, SecurityEventRepository,
    UserRepository
)
from link_shortener.infrastructure.database.manager import DatabaseManager
from link_shortener.infrastructure.database.repositories.sqlalchemy_email_verification_repository import SQLAlchemyEmailVerificationRepository
from link_shortener.infrastructure.database.repositories.sqlalchemy_password_reset_repository import SQLAlchemyPasswordResetRepository
from link_shortener.infrastructure.database.repositories.sqlalchemy_link_visit_repository import SQLAlchemyLinkVisitRepository
from link_shortener.infrastructure.database.repositories.sqlalchemy_security_event_repository import (
    SQLAlchemySecurityEventRepository,
)
from link_shortener.infrastructure.database.repositories.sqlalchemy_link_repository import SQLAlchemyLinkRepository
from link_shortener.infrastructure.database.repositories.sqlalchemy_permission_repository import SQLAlchemyPermissionRepository
from link_shortener.infrastructure.database.repositories.sqlalchemy_refresh_session_repository import SQLAlchemyRefreshSessionRepository
from link_shortener.infrastructure.database.repositories.sqlalchemy_role_repository import SQLAlchemyRoleRepository
from link_shortener.infrastructure.database.repositories.sqlalchemy_user_repository import SQLAlchemyUserRepository


class SQLAlchemyUnitOfWork(UnitOfWork):
    """
    Unit of Work that wraps a SQLAlchemy session.

    On entering the context a new session is obtained, a transaction is
    started, and all nine repositories are built -- eagerly, in ``__enter__``,
    sharing that one session. Exiting the context will roll back the
    transaction unless ``commit()`` was called explicitly.

    The ``read_only`` flag is honoured on PostgreSQL by issuing
    ``SET TRANSACTION READ ONLY``, and nowhere else: on SQLite it changes
    nothing, and it never stops ``commit()``. It is a statement of intent
    that one engine enforces, not a guarantee this class makes.
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        read_only: bool = False,
        logger: Optional[Logger] = None,
    ):
        """
        Args:
            db_manager: Configured ``DatabaseManager`` that provides sessions.
            read_only: If ``True``, the transaction asks PostgreSQL for
                ``SET TRANSACTION READ ONLY``, which refuses a write.
                On every other engine it is remembered and does nothing,
                and on no engine does it stop ``commit()`` -- a caller that
                opens a read-only unit of work and calls ``commit`` gets a
                real one.
            logger: Handed to the repositories that have something to
                report about the rows they read. Optional so that a unit
                of work assembled by hand still works; the application
                builds it through the container, which always passes one.
        """
        super().__init__(read_only=read_only)
        self.db_manager = db_manager
        self.logger = logger
        # Annotated Optional rather than inferred from the first assignment:
        # the attribute genuinely holds None until __enter__ runs, and a
        # checker told otherwise reports every later use as an error.
        self._session: Optional[Session] = None
        self._links: Optional[LinkRepository] = None
        self._users: Optional[UserRepository] = None
        self._roles: Optional[RoleRepository] = None
        self._permissions: Optional[PermissionRepository] = None
        self._refresh_sessions: Optional[RefreshSessionRepository] = None
        self._email_verifications: Optional[EmailVerificationRepository] = None
        self._password_resets: Optional[PasswordResetRepository] = None
        self._link_visits: Optional[LinkVisitRepository] = None
        self._security_events: Optional[SecurityEventRepository] = None
        self._committed = False

    # ------------------------------------------------------------------
    # Transaction control
    # ------------------------------------------------------------------
    def _start_transaction(self) -> None:
        """Begin a new transaction.

        On PostgreSQL, if ``read_only`` is ``True``, the transaction is
        explicitly set to ``READ ONLY``.
        """
        session = self._open_session
        session.begin()
        if self.read_only:
            dialect_name = session.get_bind().dialect.name
            if dialect_name == "postgresql":
                session.execute(text("SET TRANSACTION READ ONLY"))

    # ------------------------------------------------------------------
    # Context manager protocol
    # ------------------------------------------------------------------
    def __enter__(self) -> "SQLAlchemyUnitOfWork":
        """Enter the runtime context, creating a session and starting a transaction.

        Returns:
            The ``SQLAlchemyUnitOfWork`` instance itself.
        """
        if self._session is not None:
            raise RuntimeError("Unit of Work already entered")

        self._session = self.db_manager.get_session()
        self._links = SQLAlchemyLinkRepository(self._session)
        self._users = SQLAlchemyUserRepository(self._session, self.logger)
        self._roles = SQLAlchemyRoleRepository(self._session)
        self._permissions = SQLAlchemyPermissionRepository(self._session)
        self._refresh_sessions = SQLAlchemyRefreshSessionRepository(self._session)
        self._email_verifications = SQLAlchemyEmailVerificationRepository(self._session)
        self._password_resets = SQLAlchemyPasswordResetRepository(self._session)
        self._link_visits = SQLAlchemyLinkVisitRepository(self._session)
        self._security_events = SQLAlchemySecurityEventRepository(self._session)
        self._committed = False

        self._start_transaction()
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        """Exit the runtime context, committing or rolling back the transaction.

        On exception the transaction is rolled back; otherwise it is rolled back
        if the caller never called ``commit()``. The session is always closed.
        """
        # On exception, always roll back
        if exc_type:
            self.rollback()
        else:
            # If the caller never committed, we roll back to avoid
            # leaking an open transaction.
            if not self._committed:
                self.rollback()
        self._open_session.close()
        self._session = None
        self._links = None
        self._users = None
        self._roles = None
        self._permissions = None
        self._refresh_sessions = None
        self._email_verifications = None
        self._password_resets = None
        self._link_visits = None
        # The ninth, and it was the one left out: every other accessor
        # refuses after the context closes, while `security_events`
        # returned a repository still bound to the closed session --
        # measured. A write through it would open a transaction nobody
        # commits and drop a security event in silence, which is the
        # one journal that exists to have no silences in it.
        self._security_events = None

    # ------------------------------------------------------------------
    # Explicit commit / flush / rollback
    # ------------------------------------------------------------------
    def commit(self) -> None:
        """Commit the current transaction.

        Can only be called once per context; subsequent calls are no-ops.
        """
        session = self._open_session
        if session.is_active and not self._committed:
            session.commit()
            self._committed = True

    def flush(self) -> None:
        """Flush pending changes to the database without committing."""
        self._open_session.flush()

    def rollback(self) -> None:
        """Roll back the current transaction."""
        session = self._open_session
        if session.is_active:
            session.rollback()
            self._committed = False

    # ------------------------------------------------------------------
    # Session accessor
    # ------------------------------------------------------------------
    @property
    def _open_session(self) -> Session:
        """Return the session of an entered unit of work.

        The same shape the repository accessors below use, and for the same
        reason: the attribute holds ``None`` until ``__enter__`` runs, so a
        call made outside the context otherwise fails on ``None`` with a
        message naming neither the class nor the mistake.

        Returns:
            The active SQLAlchemy session.

        Raises:
            RuntimeError: If the context has not been entered.
        """
        if self._session is None:
            raise RuntimeError("Unit of Work not entered (use 'with' statement)")
        return self._session

    # ------------------------------------------------------------------
    # Repository accessors
    # ------------------------------------------------------------------
    @property
    def links(self) -> LinkRepository:
        """Return the ``LinkRepository`` bound to the current session.

        Raises:
            RuntimeError: If the context has not been entered.
        """
        if self._links is None:
            raise RuntimeError("Unit of Work not entered (use 'with' statement)")
        return self._links

    @property
    def users(self) -> UserRepository:
        """Return the ``UserRepository`` bound to the current session.

        Raises:
            RuntimeError: If the context has not been entered.
        """
        if self._users is None:
            raise RuntimeError("Unit of Work not entered")
        return self._users

    @property
    def roles(self) -> RoleRepository:
        """Return the ``RoleRepository`` bound to the current session.

        Raises:
            RuntimeError: If the context has not been entered.
        """
        if self._roles is None:
            raise RuntimeError("Unit of Work not entered")
        return self._roles

    @property
    def permissions(self) -> PermissionRepository:
        """Return the ``PermissionRepository`` bound to the current session.

        Raises:
            RuntimeError: If the context has not been entered.
        """
        if self._permissions is None:
            raise RuntimeError("Unit of Work not entered")
        return self._permissions

    @property
    def refresh_sessions(self) -> RefreshSessionRepository:
        """Return the ``RefreshSessionRepository`` bound to the current session.

        Raises:
            RuntimeError: If the context has not been entered.
        """
        if self._refresh_sessions is None:
            raise RuntimeError("Unit of Work not entered")
        return self._refresh_sessions

    @property
    def email_verifications(self) -> EmailVerificationRepository:
        """Return the ``EmailVerificationRepository`` bound to the current session.

        Raises:
            RuntimeError: If the context has not been entered.
        """
        if self._email_verifications is None:
            raise RuntimeError("Unit of Work not entered")
        return self._email_verifications

    @property
    def password_resets(self) -> PasswordResetRepository:
        """Return the ``PasswordResetRepository`` bound to the current session.

        Raises:
            RuntimeError: If the context has not been entered.
        """
        if self._password_resets is None:
            raise RuntimeError("Unit of Work not entered")
        return self._password_resets

    @property
    def link_visits(self) -> LinkVisitRepository:
        """Return the ``LinkVisitRepository`` bound to the current session.

        Raises:
            RuntimeError: If the context has not been entered.
        """
        if self._link_visits is None:
            raise RuntimeError("Unit of Work not entered")
        return self._link_visits

    @property
    def security_events(self) -> SecurityEventRepository:
        """Return the ``SecurityEventRepository`` bound to the session.

        Raises:
            RuntimeError: If the context has not been entered.
        """
        if self._security_events is None:
            raise RuntimeError("Unit of Work not entered")
        return self._security_events
