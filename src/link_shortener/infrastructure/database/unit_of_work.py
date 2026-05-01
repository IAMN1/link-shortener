"""
SQLAlchemy implementation of the Unit of Work pattern.

Manages a single database session and provides access to all repositories.
Supports read-only transactions (on PostgreSQL sets the transaction to READ ONLY).
"""

from types import TracebackType
from typing import Optional, Type
from sqlalchemy import text

from link_shortener.application import UnitOfWork
from link_shortener.domain import (
    LinkRepository, PermissionRepository,
    RoleRepository, UserRepository
)
from link_shortener.infrastructure.database.manager import DatabaseManager
from link_shortener.infrastructure.database.repositories.sqlalchemy_link_repository import SQLAlchemyLinkRepository
from link_shortener.infrastructure.database.repositories.sqlalchemy_permission_repository import SQLAlchemyPermissionRepository
from link_shortener.infrastructure.database.repositories.sqlalchemy_role_repository import SQLAlchemyRoleRepository
from link_shortener.infrastructure.database.repositories.sqlalchemy_user_repository import SQLAlchemyUserRepository


class SQLAlchemyUnitOfWork(UnitOfWork):
    """
    Unit of Work that wraps a SQLAlchemy session.

    On entering the context a new session is obtained and a transaction is
    started. Repositories are created lazily and share the same session.
    Exiting the context will roll back the transaction unless ``commit()``
    was called explicitly.

    The ``read_only`` flag is honoured on PostgreSQL by issuing
    ``SET TRANSACTION READ ONLY``.
    """

    def __init__(self, db_manager: DatabaseManager, read_only: bool = False):
        """
        Args:
            db_manager: Configured DatabaseManager that provides sessions.
            read_only: If True, the transaction is marked as read-only
                (no writes allowed), and commit will be skipped.
        """
        super().__init__(read_only=read_only)
        self.db_manager = db_manager
        self._session = None
        self._links = None
        self._users = None
        self._roles = None
        self._permissions = None
        self._committed = False

    # ------------------------------------------------------------------
    # Transaction control
    # ------------------------------------------------------------------
    def _start_transaction(self) -> None:
        """Begin a new transaction.

        On PostgreSQL, if ``read_only`` is True, the transaction is
        explicitly set to READ ONLY.
        """
        self._session.begin()
        if self.read_only:
            dialect_name = self._session.get_bind().dialect.name
            if dialect_name == "postgresql":
                self._session.execute(text("SET TRANSACTION READ ONLY"))

    # ------------------------------------------------------------------
    # Context manager protocol
    # ------------------------------------------------------------------
    def __enter__(self) -> "SQLAlchemyUnitOfWork":
        if self._session is not None:
            raise RuntimeError("Unit of Work already entered")

        self._session = self.db_manager.get_session()
        self._links = SQLAlchemyLinkRepository(self._session)
        self._users = SQLAlchemyUserRepository(self._session)
        self._roles = SQLAlchemyRoleRepository(self._session)
        self._permissions = SQLAlchemyPermissionRepository(self._session)
        self._committed = False

        self._start_transaction()
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        # On exception, always roll back
        if exc_type:
            self.rollback()
        else:
            # If the caller never committed, we roll back to avoid
            # leaking an open transaction.
            if not self._committed:
                self.rollback()
        self._session.close()
        self._session = None
        self._links = None
        self._users = None
        self._roles = None
        self._permissions = None

    # ------------------------------------------------------------------
    # Explicit commit / flush / rollback
    # ------------------------------------------------------------------
    def commit(self) -> None:
        """
        Commit the current transaction.

        Can only be called once per context; subsequent calls are no-ops.
        """
        if self._session.is_active and not self._committed:
            self._session.commit()
            self._committed = True

    def flush(self) -> None:
        """Flush pending changes to the database without committing."""
        self._session.flush()

    def rollback(self) -> None:
        """Roll back the current transaction."""
        if self._session.is_active:
            self._session.rollback()
            self._committed = False

    # ------------------------------------------------------------------
    # Repository accessors
    # ------------------------------------------------------------------
    @property
    def links(self) -> LinkRepository:
        """Return the LinkRepository bound to the current session.

        Raises:
            RuntimeError: If the context has not been entered.
        """
        if self._links is None:
            raise RuntimeError("Unit of Work not entered (use 'with' statement)")
        return self._links

    @property
    def users(self) -> UserRepository:
        if self._users is None:
            raise RuntimeError("Unit of Work not entered")
        return self._users

    @property
    def roles(self) -> RoleRepository:
        if self._roles is None:
            raise RuntimeError("Unit of Work not entered")
        return self._roles

    @property
    def permissions(self) -> PermissionRepository:
        if self._permissions is None:
            raise RuntimeError("Unit of Work not entered")
        return self._permissions