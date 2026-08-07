from enum import Enum


class SystemPermissions(Enum):
    """
    Enumeration of all predefined system permission names.

    These correspond to the permissions defined in the RBAC configuration
    file (roles.yaml) and are used throughout the application for
    authorization checks.

    Each member's value is the exact permission string stored in the
    database and expected by the authorization service.
    """
    # --- Link permissions ---
    LINK_CREATE = "link:create"
    LINK_VIEW_OWN = "link:view_own"
    LINK_DELETE_OWN = "link:delete_own"
    LINK_DELETE_ANY = "link:delete_any"

    # --- Statistics permissions ---
    STATS_VIEW_BASIC = "stats:view_basic"
    STATS_VIEW_FULL = "stats:view_full"
    STATS_VIEW_ANY = "stats:view_any"

    # --- Admin permissions ---
    ADMIN_VIEW_USERS = "admin:view_users"
    ADMIN_MANAGE_USERS = "admin:manage_users"
    ADMIN_VIEW_ROLES = "admin:view_roles"
    ADMIN_MANAGE_ROLES = "admin:manage_roles"
    ADMIN_VIEW_SYSTEM_HEALTH = "admin:view_system_health"
    ADMIN_ALL = "admin:all"

    @classmethod
    def all_values(cls) -> list[str]:
        """Return all permission string values for use in UI/validation."""
        return [p.value for p in cls]
