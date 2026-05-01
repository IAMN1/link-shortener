from dataclasses import dataclass
from typing import List, Optional

from link_shortener.application.ports.auth.auth_service import AuthenticationService
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.domain import (
    User, DomainError, ValidationError,
    Email, PasswordHash, Role
)


@dataclass
class UserManagementService:
    """
    Application service for user CRUD and role assignment.

    Coordinates between repositories and authentication services.
    Authorization checks are performed by the calling use case.
    """
    auth_service: AuthenticationService
    default_role_name: str

    def create_user(
            self,
            uow: UnitOfWork,
            email: str,
            password: str,
            roles: Optional[List[Role]] = None,
            is_active: bool = True,
    ) -> User:
        """
        Create a new user.

        Args:
            uow: Unit of work.
            email: User's email.
            password: Plain-text password.
            roles: Roles to assign; if None, the default role is used.
            is_active: Whether the account is active.

        Returns:
            The created User entity.

        Raises:
            ValidationError: If email is invalid or already registered.
        """

        # Validate email format via value object
        try:
            email_vo = Email(email)
        except ValueError as e:
            raise ValidationError(str(e), field="email")
        
        # Check uniqueness
        if uow.users.find_by_email(email_vo):
            raise ValidationError("Email already registered", field="email")
        
        # Hash password using authentication service
        hashed_password = self.auth_service.hash_password(password)
        password_hash_vo = PasswordHash(hashed_password)

        # Determine roles to assign
        assigned_roles = roles if roles is not None else []
        if not assigned_roles:
            default_role = uow.roles.get_by_name(self.default_role_name)
            if not default_role:
                raise DomainError(
                    f"Default role '{self.default_role_name}' not found",
                    code="CONFIGURATION_ERROR"
                )
            assigned_roles = [self.default_role]
        
        # Create domain entity (business rules encapsulated inside)
        user = User.create(
            email=email_vo,
            password_hash=password_hash_vo,
            roles=assigned_roles,
        )
        user.is_active = is_active

        # Persist
        saved_user = uow.users.save(user)
        return saved_user
    
    def update_roles(self, uow: UnitOfWork, user_id: str, roles: List[Role]) -> User:
        """
        Replace roles of an existing user.

        Args:
            uow: Unit of work.
            user_id: User ID.
            roles: New list of roles.

        Returns:
            Updated User.

        Raises:
            DomainError: If user not found.
        """

        user = uow.users.find_by_id(user_id)
        if not user:
            raise DomainError(f"User with id {user_id} not found", code="USER_NOT_FOUND")
        
        user.roles = roles
        return uow.users.save(user)
    
    def add_role(self, uow: UnitOfWork, user_id: str, role: Role) -> User:
        """
        Add a single role to a user if not already present.

        Args:
            uow: Unit of work.
            user_id: User ID.
            role: Role to add.

        Returns:
            Updated User.
        """
        user = uow.users.find_by_id(user_id)
        if not user:
            raise DomainError(f"User with id {user_id} not found", code="USER_NOT_FOUND")
        
        if role not in user.roles:
            user.roles.append(role)
            user = uow.users.save(user)
        return user
    
    def remove_role(self, uow: UnitOfWork, user_id: str, role_name: str) -> User:
        """
        Remove a role from a user by role name.

        Args:
            uow: Unit of work.
            user_id: User ID.
            role_name: Name of the role to remove.

        Returns:
            Updated User.
        """
        user = uow.users.find_by_id(user_id)
        if not user:
            raise DomainError(f"User with id {user_id} not found", code="USER_NOT_FOUND")
        
        user.roles = [r for r in user.roles if r.name != role_name]
        return uow.users.save(user)
    
    def deactivate_user(self, uow: UnitOfWork, user_id: str) -> User:
        """
        Deactivate a user (soft delete).

        Args:
            uow: Unit of work.
            user_id: User ID.

        Returns:
            Updated User.
        """
        user = uow.users.find_by_id(user_id)
        if not user:
            raise DomainError(f"User with id {user_id} not found", code="USER_NOT_FOUND")
        user.deactivate()

        return uow.users.save(user)
    
    def activate_user(self, uow: UnitOfWork, user_id: str) -> User:
        """
        Activate a previously deactivated user.

        Args:
            uow: Unit of work.
            user_id: User ID.

        Returns:
            Updated User.
        """
        user = uow.users.find_by_id(user_id)
        if not user:
            raise DomainError(f"User with id {user_id} not found", code="USER_NOT_FOUND")
        user.activate()
        return uow.users.save(user)
    
    def list_users(self, uow: UnitOfWork, limit: int = 100, offset: int = 0) -> List[User]:
        """
        Retrieve a paginated list of users.

        Args:
            uow: Unit of work (read-only recommended).
            limit: Max users to return.
            offset: Pagination offset.

        Returns:
            List of User entities.
        """
        return uow.users.list_all(limit=limit, offset=offset)
    
    def get_user_by_id(self, uow: UnitOfWork, user_id: str) -> Optional[User]:
        """
        Find a user by ID.

        Args:
            uow: Unit of work.
            user_id: User ID.

        Returns:
            User if found, else None.
        """
        return uow.users.find_by_id(user_id)
    
    def get_user_by_email(self, uow: UnitOfWork, email: str) -> Optional[User]:
        """
        Find a user by email.

        Args:
            uow: Unit of work.
            email: Email string.

        Returns:
            User if found, else None.
        """
        try:
            email_vo = Email(email)
            return uow.users.find_by_email(email_vo)
        except ValueError:
            return None
    
    def delete_user(self, uow: UnitOfWork, user_id: str) -> bool:
        """
        Permanently delete a user.

        Args:
            uow: Unit of work.
            user_id: User ID.

        Returns:
            True if deleted, False if not found.
        """
        return uow.users.delete(user_id)
