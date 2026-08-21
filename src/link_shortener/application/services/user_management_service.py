from dataclasses import dataclass
from typing import List, Optional

from link_shortener.application.ports.auth.auth_service import AuthenticationService
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.domain import (
    User, DomainError, ValidationError,
    Email, PasswordHash, Role
)
from link_shortener.domain.i18n import N_
from link_shortener.domain.policies.role_policy import (
    require_roles_are_assignable,
)


@dataclass
class UserManagementService:
    """
    Application service for user CRUD and role assignment.

    Coordinates between repositories and authentication services.
    Authorization checks are performed by the calling use case.
    """
    authentication_service: AuthenticationService
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

        # Validated by the value object, and left to raise. The wrap that
        # used to be here caught ``ValueError`` -- which a ``ValidationError``
        # is not, so it never ran -- and had it run it would have replaced a
        # marked sentence with a finished one, costing the address error its
        # translation on the way out.
        email_vo = Email(email)
        
        # Check uniqueness
        if uow.users.find_by_email(email_vo):
            raise ValidationError(N_("Email already registered"), field="email")
        
        # Hash password using authentication service
        hashed_password = self.authentication_service.hash_password(password)
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
            assigned_roles = [default_role]
        
        # Create domain entity (business rules encapsulated inside)
        user = User.create(
            email=email_vo,
            password_hash=password_hash_vo,
            roles=assigned_roles,
            # Confirmed on creation, unlike self-registration. Nobody is
            # going to mail this person a link -- an administrator typed
            # the address and vouches for it -- and an account created
            # through the admin API that then cannot sign in is a broken
            # tool with no visible cause. The confirmation exists to stop
            # a stranger claiming an address they do not read; that is not
            # what is happening here.
            email_verified=True,
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
            raise DomainError(
                      f"User with id {user_id} not found",
                      code="USER_NOT_FOUND",
                      template=N_("User with id %(id)s not found"),
                      params={"id": user_id},
                  )
        
        # ``User.create`` asks this on the way in; this is the other way
        # a role reaches an account, and it goes around the factory.
        require_roles_are_assignable(roles)

        user.roles = roles
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
            raise DomainError(
                      f"User with id {user_id} not found",
                      code="USER_NOT_FOUND",
                      template=N_("User with id %(id)s not found"),
                      params={"id": user_id},
                  )
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
            raise DomainError(
                      f"User with id {user_id} not found",
                      code="USER_NOT_FOUND",
                      template=N_("User with id %(id)s not found"),
                      params={"id": user_id},
                  )
        user.activate()
        return uow.users.save(user)
    
    def update_password(
        self, uow: UnitOfWork, user: User, new_password: str
    ) -> int:
        """
        Replace a user's password, and retire everything the old one held.

        The whole act, not the hash alone. A password change retires every
        session the account has and every reset link outstanding for it,
        and that is written down in ``docs/decisions.md``: "A new request
        retires the links outstanding, and so does any password change."
        The reason is what a password change is usually *for* -- somebody
        else may have the old one -- and a change that leaves their
        session open has changed nothing they care about, while a reset
        link that outlives it is that stranger still holding a way back
        in.

        All of it here rather than in the callers, because there are three
        callers and the rule held in two. ``flask security
        reset-password`` -- the operator's path, reached for an account
        believed compromised -- replaced the hash and left every session
        live and every mailed link working. A rule stated in the callers
        is a rule the next caller does not know about; stated here, it is
        the only door.

        Args:
            uow: Unit of work.
            user: The user whose password is being changed.
            new_password: New plain-text password.

        Returns:
            How many sessions were revoked, which is what the audit
            journal records alongside the change.

        Raises:
            ValidationError: If the password is empty, or the policy
                refuses it. Raised before anything is retired, so a
                refused password leaves the account exactly as it was.
        """
        if not new_password:
            raise ValidationError(N_("Password must not be empty"), field="password")

        # The policy lives inside hashing, so a password it refuses is
        # refused here before a single session is touched.
        hashed = self.authentication_service.hash_password(new_password)
        user.password_hash = PasswordHash(hashed)
        uow.users.save(user)

        # The likeliest reason somebody changes a password in a hurry is
        # that a reset they did not ask for arrived in their mailbox, and
        # a link that outlives the change is that stranger still holding
        # the account.
        uow.password_resets.invalidate_for_user(user.id)

        return uow.refresh_sessions.revoke_all_for_user(user.id)

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
