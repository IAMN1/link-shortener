from .entities.link import Link
from .entities.user import User
from .entities.role import Role
from .entities.permission import Permission
from .entities.refresh_session import RefreshSession
from .entities.email_verification import EmailVerification
from .entities.password_reset import PasswordReset
from .entities.link_visit import (
    LinkVisit, VisitBreakdown, VisitBucket, VisitSummary, VisitsOnADay,
)

from .policies.hash_calculator import HashCalculator
from .policies.code_generator import CodeGenerator

from .repositories.user_repository import UserRepository
from .repositories.role_repository import RoleRepository
from .repositories.permission_repository import PermissionRepository
from .repositories.link_repository import (
    LinkRepository,
    ServiceLinkStats,
    UserLinkStats,
)
from .repositories.refresh_session_repository import RefreshSessionRepository
from .repositories.email_verification_repository import EmailVerificationRepository
from .repositories.password_reset_repository import PasswordResetRepository
from .repositories.link_visit_repository import LinkVisitRepository
from .repositories.security_event_repository import SecurityEventRepository

from .value_objects.original_url import OriginalUrl
from .value_objects.short_code import ShortCode
from .value_objects.url_hash import UrlHash
from .value_objects.email import Email
from .value_objects.password_hash import PasswordHash
from .value_objects.owner_id import OwnerID
from .value_objects.dedup_scope import DedupScope
from .value_objects.visitor import anonymise_address, classify_client

from .exceptions import (
    DomainError, LinkNotFoundError, ValidationError,
    CodeGenerationError, LinkCodeTakenError, LinkConflictError,
    LinkExpiredError,
    GuestLinkLimitExceededError,
    RoleNotFoundError, RoleAlreadyExistsError, RoleIsSystemError,
    PermissionDeniedError,
    RoleNotAssignableError,
    PermissionsNotFoundError
)

from .system_permissions import SystemPermissions

__all__ = [
    # Entities
    "Link",
    "User",
    "Role",
    "Permission",
    "RefreshSession",
    "EmailVerification",
    "PasswordReset",
    "LinkVisit",
    "VisitsOnADay",
    "VisitBucket",
    "VisitBreakdown",
    "VisitSummary",

    # Policies
    "HashCalculator",
    "CodeGenerator",
    
    # Repositories
    "LinkRepository",
    "ServiceLinkStats",
    "UserLinkStats",
    "RefreshSessionRepository",
    "EmailVerificationRepository",
    "PasswordResetRepository",
    "LinkVisitRepository",
    "SecurityEventRepository",
    "UserRepository",
    "RoleRepository",
    "PermissionRepository",
    
    # Value Objects
    "OriginalUrl",
    "ShortCode",
    "UrlHash",
    "Email",
    "PasswordHash",
    "OwnerID",
    "DedupScope",
    "anonymise_address",
    "classify_client",

    # Exceptions
    "DomainError",
    "ValidationError",
    "LinkNotFoundError",
    "CodeGenerationError",
    "LinkCodeTakenError",
    "LinkConflictError",
    "LinkExpiredError",
    "GuestLinkLimitExceededError",
    "RoleNotFoundError",
    "RoleAlreadyExistsError",
    "RoleIsSystemError",
    "PermissionDeniedError",
    "RoleNotAssignableError",
    "PermissionsNotFoundError",

    # System permissions
    "SystemPermissions"
]
