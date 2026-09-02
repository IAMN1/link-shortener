from typing import Protocol
from abc import ABC, abstractmethod

from link_shortener.domain import (
    EmailVerificationRepository, LinkRepository, LinkVisitRepository,
    PasswordResetRepository, PermissionRepository, RefreshSessionRepository,
    RoleRepository, SecurityEventRepository, UserRepository
)

class UnitOfWork(ABC):
    """
    Abstract Unit of Work.

    Manages a single transaction and provides access to repositories
    within a consistent session. Supports read-only mode to avoid
    unnecessary transaction overhead.
    """

    def __init__(self, read_only: bool = False):
        """
        Args:
            read_only: If True, the transaction is not intended for writes.
                The implementation may skip commit, use a read-only connection,
                or set transaction isolation.
        """
        self.read_only = read_only

    # ----- Abstract properties for accessing repositories -----
    @property
    @abstractmethod
    def links(self) -> LinkRepository:
        """Return a LinkRepository bound to the current session."""
        ...

    @property
    @abstractmethod
    def users(self) -> UserRepository:
        """Return a UserRepository bound to the current session."""
        ...

    @property
    @abstractmethod
    def roles(self) -> RoleRepository:
        """Return a RoleRepository bound to the current session."""
        ...

    @property
    @abstractmethod
    def permissions(self) -> PermissionRepository:
        """Return a PermissionRepository bound to the current session."""
        ...

    @property
    @abstractmethod
    def refresh_sessions(self) -> RefreshSessionRepository:
        """Return a RefreshSessionRepository bound to the current session."""
        ...

    @property
    @abstractmethod
    def email_verifications(self) -> EmailVerificationRepository:
        """Return an EmailVerificationRepository bound to the current session."""
        ...

    @property
    @abstractmethod
    def password_resets(self) -> PasswordResetRepository:
        """Return a PasswordResetRepository bound to the current session."""
        ...

    @property
    @abstractmethod
    def link_visits(self) -> LinkVisitRepository:
        """Return a LinkVisitRepository bound to the current session."""
        ...

    @property
    @abstractmethod
    def security_events(self) -> SecurityEventRepository:
        """Return a SecurityEventRepository bound to the current session."""
        ...

    # ----- Transaction management -----
    @abstractmethod
    def commit(self) -> None:
        """Commit the current transaction."""
        ...

    @abstractmethod
    def flush(self) -> None:
        """Flush pending changes to the database without committing."""
        ...

    @abstractmethod
    def rollback(self) -> None:
        """Rollback the current transaction."""
        ...

    # ----- Context manager support -----
    @abstractmethod
    def __enter__(self) -> "UnitOfWork":
        """Enter the context, starting a transaction."""
        ...

    @abstractmethod
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the context, committing or rolling back."""
        ...


class UnitOfWorkFactory(Protocol):
    """
    What a caller needs in order to open a unit of work.

    Declared as a protocol rather than as ``Callable[[], UnitOfWork]``,
    because that spelling says the factory takes nothing while every
    read-only caller in the service passes ``read_only=True`` -- a flag the
    unit of work itself accepts and honours. The declaration described a
    narrower interface than the one those callers use.
    """

    def __call__(self, read_only: bool = False) -> UnitOfWork:
        """
        Open a unit of work.

        Args:
            read_only: If True, the transaction is not intended for writes.

        Returns:
            A unit of work that has not been entered yet.
        """
        ...
