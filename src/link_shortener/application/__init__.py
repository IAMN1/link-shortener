"""
The order the domain's rules are applied in, and the ports that costs.

What may go in this layer is decided by what it may import: the domain, and
the standard library. No framework, no session, no ORM, no configuration
object -- a use case that needed one of those would be deciding how this
deployment is built rather than what the service does. Whatever it needs
from outside is named as an interface in ``application/ports`` and
implemented by ``infrastructure``, so the dependency points inwards even
where the call goes out.

Inside, the kinds of thing are told apart by what they open. A *use case*
is one act a caller can ask for and opens its own unit of work. A *service*
is work several use cases share and takes the unit of work its caller
opened. A *facade* is what the web layer holds and opens nothing. A *DTO*
holds values and decides nothing, and a *port* is a name for something
outside. Each directory's own docstring says which of those it takes, and
what its exceptions are.

The names gathered below are the layer's vocabulary, so that a caller
writes ``from link_shortener.application import LinkService`` rather than
naming the module it happens to sit in -- which is also what keeps moving a
file inside the layer from being a change to everything that reads it.
"""

# ------------------------------------------------------------------
# DTOs (Data Transfer Objects)
# ------------------------------------------------------------------
from .dtos.link import ShortLinkResponse, ExtendedLinkInfoResponse
from .dtos.batch import BatchItemResponse, BatchCreateResponse
from .dtos.stats import StatsItemResponse, ServiceStatsResponse
from .dtos.user import UserResponse
from .dtos.auth import LoginResponse
from .dtos.admin.role import RoleResponse
from .dtos.admin.permission import PermissionResponse
from .dtos.current_user_info import CurrentUserInfo
from .dtos.user_activity import UserActivityResponse

# ------------------------------------------------------------------
# Ports (interfaces)
# ------------------------------------------------------------------
from .ports.cache.cache_health import CacheHealth
from .ports.cache.link_cache import LinkCache
from .ports.cache.link_service_stats_cache import StatsCache
from .ports.cache.service_cache import ServiceCache
from .ports.cache.redirect_cache import CachedRedirect, RedirectCache
from .ports.logger.audit import AuditEvent, AuditLogger
from .ports.logger.logger import Logger
from .ports.mail_templates import MailTemplates
from .ports.mailer import Mailer, MailDeliveryError
from .ports.rate_limiter import RateLimiter
from .ports.task_queue import TaskQueue
from .ports.auth.auth_service import AuthenticationService
from .ports.auth.authorization_service import AuthorizationService
from .ports.uow import UnitOfWork, UnitOfWorkFactory
from .ports.health_check import HealthCheck
from .ports.journal_reader import (
    Journal, JournalLine, JournalPage, JournalReaderPort,
)

# ------------------------------------------------------------------
# Facades the web layer holds, and the services use cases reach down to.
# Two kinds of object, two directories: see the docstring in each.
# ------------------------------------------------------------------
from .facades.admin_service import AdminService
from .facades.auth_service import AuthService
from .facades.link_service import LinkService
from .services.role_management_service import RoleManagementService
from .services.user_management_service import UserManagementService

# ------------------------------------------------------------------
# Use Cases
# ------------------------------------------------------------------
from .use_cases.batch.batch_create_links import BatchCreateLinksUseCase
from .use_cases.batch.creator import BatchLinkCreator
from .use_cases.batch.fetcher import BatchLinkFetcher
from .use_cases.batch.grouper import UrlGrouper
from .use_cases.batch.response_builder import BatchResponseBuilder

from .use_cases.links.create_short_link import CreateShortLinkUseCase
from .use_cases.links.get_link_info import GetLinkInfoUseCase
from .use_cases.links.get_extended_link_info import GetExtendedLinkInfoUseCase
from .use_cases.links.get_user_links import GetUserLinksUseCase
from .use_cases.links.redirect_link import RedirectLinkUseCase
from .use_cases.links.delete_link import DeleteLinkUseCase
from .use_cases.links.update_link_stats import UpdateLinkStatsUseCase

from .use_cases.journals.read_journal import ReadJournalUseCase

from .use_cases.stats.get_service_health import GetServiceHealthUseCase
from .use_cases.stats.get_service_stats import GetServiceStatsUseCase
from .use_cases.stats.get_visit_stats import GetVisitStatsUseCase
from .use_cases.stats.get_user_activity_stats import GetUserActivityStatsUseCase

from .use_cases.admin.links.clean_expired_links import CleanExpiredLinksUseCase
from .use_cases.admin.links.roll_up_visits import RollUpVisitsUseCase
from .use_cases.admin.security.roll_up_security_events import (
    RollUpSecurityEventsUseCase,
)
from .use_cases.admin.links.get_recent_links import GetRecentLinksUseCase
from .use_cases.admin.database.seed_database import SeedDatabaseUseCase

from .use_cases.admin.roles.create_role import CreateRoleUseCase
from .use_cases.admin.roles.update_role_permissions import UpdateRolePermissionsUseCase
from .use_cases.admin.roles.delete_role import DeleteRoleUseCase
from .use_cases.admin.roles.list_roles import ListRolesUseCase
from .use_cases.admin.roles.get_role import GetRoleUseCase

from .use_cases.admin.users.create_user import CreateUserUseCase
from .use_cases.admin.users.update_user_role import UpdateUserRolesUseCase
from .use_cases.admin.users.confirm_user_email import ConfirmUserEmailUseCase
from .use_cases.admin.users.deactivate_user import DeactivateUserUseCase
from .use_cases.admin.users.activate_user import ActivateUserUseCase
from .use_cases.admin.users.list_user import ListUsersUseCase
from .use_cases.admin.users.get_user import GetUserUseCase
from .use_cases.admin.users.delete_user import DeleteUserUseCase

from .use_cases.auth.change_password import ChangePasswordUseCase
from .use_cases.auth.login import LoginUseCase
from .use_cases.auth.register import RegisterUseCase
from .use_cases.auth.request_password_reset import (
    PasswordResetOutcome, RequestPasswordResetUseCase,
)
from .use_cases.auth.reset_password import ResetPasswordUseCase
from .use_cases.auth.resend_verification import ResendVerificationUseCase
from .use_cases.auth.send_account_exists_email import SendAccountExistsEmailUseCase
from .use_cases.auth.send_password_reset_email import SendPasswordResetEmailUseCase
from .use_cases.auth.send_verification_email import SendVerificationEmailUseCase
from .use_cases.auth.verify_email import VerifyEmailUseCase

from .use_cases.admin.users.clean_unverified_accounts import (
    CleanUnverifiedAccountsUseCase,
)

# ------------------------------------------------------------------
# Context
# ------------------------------------------------------------------
from .context import RequestContext

# ------------------------------------------------------------------
# Utilities
# ------------------------------------------------------------------
from .utils.cache_key_builder import CacheKeyBuilder
from .utils.url_utils import build_short_url

__all__ = [
    # DTOs
    "ShortLinkResponse",
    "ExtendedLinkInfoResponse",
    "BatchItemResponse",
    "BatchCreateResponse",
    "StatsItemResponse",
    "ServiceStatsResponse",
    "UserResponse",
    "LoginResponse",
    "RoleResponse",
    "PermissionResponse",
    "CurrentUserInfo",
    "UserActivityResponse",

    # Ports
    "CacheHealth",
    "LinkCache",
    "StatsCache",
    "ServiceCache",
    "CachedRedirect",
    "RedirectCache",
    "AuditEvent",
    "AuditLogger",
    "Logger",
    "Mailer",
    "MailDeliveryError",
    "MailTemplates",
    "RateLimiter",
    "TaskQueue",
    "AuthenticationService",
    "AuthorizationService",
    "UnitOfWork",
    "UnitOfWorkFactory",
    "HealthCheck",
    "Journal",
    "JournalLine",
    "JournalPage",
    "JournalReaderPort",

    # Services
    "AdminService",
    "AuthService",
    "LinkService",
    "RoleManagementService",
    "UserManagementService",

    # Use Cases
    "BatchCreateLinksUseCase",
    "BatchLinkCreator",
    "BatchLinkFetcher",
    "UrlGrouper",
    "BatchResponseBuilder",

    "CreateShortLinkUseCase",
    "GetLinkInfoUseCase",
    "GetExtendedLinkInfoUseCase",
    "GetUserLinksUseCase",
    "RedirectLinkUseCase",
    "DeleteLinkUseCase",
    "UpdateLinkStatsUseCase",

    "ReadJournalUseCase",

    "GetServiceHealthUseCase",
    "GetServiceStatsUseCase",
    "GetVisitStatsUseCase",
    "GetUserActivityStatsUseCase",

    "CleanExpiredLinksUseCase",
    "RollUpVisitsUseCase",
    "RollUpSecurityEventsUseCase",
    "GetRecentLinksUseCase",
    "SeedDatabaseUseCase",
    "CreateRoleUseCase",
    "UpdateRolePermissionsUseCase",
    "DeleteRoleUseCase",
    "ListRolesUseCase",
    "GetRoleUseCase",
    "CreateUserUseCase",
    "UpdateUserRolesUseCase",
    "ConfirmUserEmailUseCase",
    "DeactivateUserUseCase",
    "ActivateUserUseCase",
    "ListUsersUseCase",
    "GetUserUseCase",
    "DeleteUserUseCase",

    "ChangePasswordUseCase",
    "LoginUseCase",
    "PasswordResetOutcome",
    "RegisterUseCase",
    "RequestPasswordResetUseCase",
    "ResetPasswordUseCase",
    "ResendVerificationUseCase",
    "SendAccountExistsEmailUseCase",
    "SendPasswordResetEmailUseCase",
    "SendVerificationEmailUseCase",
    "VerifyEmailUseCase",
    "CleanUnverifiedAccountsUseCase",

    # Context
    "RequestContext",

    # Utilities
    "CacheKeyBuilder",
    "build_short_url",
]
