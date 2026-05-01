# ------------------------------------------------------------------
# DTOs (Data Transfer Objects)
# ------------------------------------------------------------------
from .dtos.link import ShortLinkResponse, ExtendedLinkInfoResponse
from .dtos.batch import BatchItemResponse, BatchCreateResponse
from .dtos.stats import StatsItemResponse, ServiceStatsResponse
from .dtos.user import UserResponse
from .dtos.auth import LoginResponse, RegisterResponse
from .dtos.admin.role import RoleResponse
from .dtos.admin.permission import PermissionResponse
from .dtos.current_user_info import CurrentUserInfo

# ------------------------------------------------------------------
# Ports (interfaces)
# ------------------------------------------------------------------
from .ports.cache.link_cache import LinkCache
from .ports.cache.link_service_stats_cache import StatsCache
from .ports.cache.redirect_cache import RedirectCache
from .ports.logger.audit import AuditLogger
from .ports.logger.logger import Logger
from .ports.rate_limiter import RateLimiter
from .ports.task_queue import TaskQueue
from .ports.auth.auth_service import AuthenticationService
from .ports.auth.authorization_service import AuthorizationService
from .ports.uow import UnitOfWork

# ------------------------------------------------------------------
# Application Services (facades)
# ------------------------------------------------------------------
from .services.link_service import LinkService
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
from .use_cases.links.redirect_link import RedirectLinkUseCase
from .use_cases.links.delete_link import DeleteLinkUseCase
from .use_cases.links.update_link_stats import UpdateLinkStatsUseCase
from .use_cases.stats.get_service_stats import GetServiceStatsUseCase

from .use_cases.admin.links.clean_expired_links import CleanExpiredLinksUseCase
from .use_cases.admin.links.get_recent_links import GetRecentLinksUseCase
from .use_cases.admin.database.seed_database import SeedDatabaseUseCase

from .use_cases.admin.roles.create_role import CreateRoleUseCase
from .use_cases.admin.roles.update_role_permissions import UpdateRolePermissionsUseCase
from .use_cases.admin.roles.delete_role import DeleteRoleUseCase
from .use_cases.admin.roles.list_roles import ListRolesUseCase
from .use_cases.admin.roles.get_role import GetRoleUseCase

from .use_cases.admin.users.create_user import CreateUserUseCase
from .use_cases.admin.users.update_user_role import UpdateUserRolesUseCase
from .use_cases.admin.users.deactivate_user import DeactivateUserUseCase
from .use_cases.admin.users.activate_user import ActivateUserUseCase
from .use_cases.admin.users.list_user import ListUsersUseCase
from .use_cases.admin.users.get_user import GetUserUseCase
from .use_cases.admin.users.delete_user import DeleteUserUseCase

from .use_cases.auth.login import LoginUseCase
from .use_cases.auth.register import RegisterUseCase

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
    "RegisterResponse",
    "RoleResponse",
    "PermissionResponse",
    "CurrentUserInfo",

    # Ports
    "LinkCache",
    "StatsCache",
    "RedirectCache",
    "AuditLogger",
    "Logger",
    "RateLimiter",
    "TaskQueue",
    "AuthenticationService",
    "AuthorizationService",
    "UnitOfWork",

    # Services
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
    "RedirectLinkUseCase",
    "DeleteLinkUseCase",
    "UpdateLinkStatsUseCase",
    "GetServiceStatsUseCase",

    "CleanExpiredLinksUseCase",
    "GetRecentLinksUseCase",
    "SeedDatabaseUseCase",
    "CreateRoleUseCase",
    "UpdateRolePermissionsUseCase",
    "DeleteRoleUseCase",
    "ListRolesUseCase",
    "GetRoleUseCase",
    "CreateUserUseCase",
    "UpdateUserRolesUseCase",
    "DeactivateUserUseCase",
    "ActivateUserUseCase",
    "ListUsersUseCase",
    "GetUserUseCase",
    "DeleteUserUseCase",

    "LoginUseCase",
    "RegisterUseCase",

    # Context
    "RequestContext",

    # Utilities
    "CacheKeyBuilder",
    "build_short_url",
]