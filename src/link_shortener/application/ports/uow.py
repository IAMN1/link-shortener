from abc import ABC, abstractmethod

from link_shortener.domain import (
    LinkRepository, PermissionRepository, 
    RoleRepository, UserRepository
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
