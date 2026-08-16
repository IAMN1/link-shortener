"""
Administrative API controller.

Handles endpoints for managing users, roles, viewing user statistics,
and checking service health.  All methods require the corresponding
administrative permissions.
"""

from typing import Any, Dict

from flask import Blueprint, jsonify, request
from link_shortener.application import AdminService
from link_shortener.domain import DomainError, SystemPermissions
from link_shortener.web.schemas.admin.admin_request import (
    CreateRoleRequest, CreateUserRequest,
    UpdateRolePermissionsRequest, UpdateUserRolesRequest
)
from link_shortener.web.schemas.admin.admin_responses import RoleResponseSchema, UserResponseSchema
from link_shortener.web.schemas.link import ShortLinkResponse
from link_shortener.web.security.context import create_request_context
from link_shortener.web.security.decorators import require_permission
from link_shortener.domain.i18n import N_


class AdminApiController:
    """
    RESTful controller for administrative operations.

    Exposes endpoints for managing users, roles, as well as
    viewing user statistics and service health.
    """

    def __init__(self, admin_service: AdminService):
        self.admin_service = admin_service
        self.bp = Blueprint("admin_api", __name__, url_prefix="/api/v1/admin")
        self._register_routes()

    def _register_routes(self):
        # Users
        self.bp.add_url_rule("/users", view_func=self.create_user, methods=["POST"])
        self.bp.add_url_rule("/users", view_func=self.list_users, methods=["GET"])
        self.bp.add_url_rule("/users/<user_id>", view_func=self.get_user, methods=["GET"])
        self.bp.add_url_rule("/users/<user_id>/roles", view_func=self.update_user_roles, methods=["PUT"])
        self.bp.add_url_rule("/users/<user_id>/verify-email", view_func=self.confirm_user_email, methods=["POST"])
        self.bp.add_url_rule("/users/<user_id>/resend-verification", view_func=self.resend_verification, methods=["POST"])
        self.bp.add_url_rule("/users/<user_id>/deactivate", view_func=self.deactivate_user, methods=["POST"])
        self.bp.add_url_rule("/users/<user_id>/activate", view_func=self.activate_user, methods=["POST"])
        self.bp.add_url_rule("/users/<user_id>", view_func=self.delete_user, methods=["DELETE"])
        self.bp.add_url_rule("/users/<user_id>/stats", view_func=self.get_user_stats, methods=["GET"])
        # Roles
        self.bp.add_url_rule("/roles", view_func=self.create_role, methods=["POST"])
        self.bp.add_url_rule("/roles", view_func=self.list_roles, methods=["GET"])
        self.bp.add_url_rule("/roles/<role_name>", view_func=self.get_role, methods=["GET"])
        self.bp.add_url_rule("/roles/<role_name>/permissions", view_func=self.update_role_permissions, methods=["PUT"])
        self.bp.add_url_rule("/roles/<role_name>", view_func=self.delete_role, methods=["DELETE"])
        # Health
        self.bp.add_url_rule("/health", view_func=self.get_health, methods=["GET"])

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------
    @require_permission(SystemPermissions.ADMIN_MANAGE_USERS.value)
    def create_user(self):
        """
        Handle POST /api/v1/admin/users – create a new user.

        Reads JSON body with ``email``, ``password``, ``roles``, ``is_active``.
        Returns the created user's data with status 201.
        """
        data = request.get_json() or {}
        validated = CreateUserRequest(**data)
        context = create_request_context()
        result = self.admin_service.create_user(
            email=validated.email,
            password=validated.password,
            context=context,
            role_names=validated.roles,
            is_active=validated.is_active,
        )
        return jsonify(UserResponseSchema.from_dto(result).model_dump()), 201

    @require_permission(SystemPermissions.ADMIN_VIEW_USERS.value)
    def list_users(self):
        """
        Handle GET /api/v1/admin/users – list users.

        Supports ``limit`` and ``offset`` query parameters.
        """
        context = create_request_context()
        limit = request.args.get("limit", 100, type=int)
        offset = request.args.get("offset", 0, type=int)
        users = self.admin_service.list_users(context, limit=limit, offset=offset)
        return jsonify([UserResponseSchema.from_dto(u).model_dump() for u in users])

    @require_permission(SystemPermissions.ADMIN_VIEW_USERS.value)
    def get_user(self, user_id):
        """
        Handle ``GET /api/v1/admin/users/<user_id>`` – get a single user.

        Returns 404 if the user is not found.
        """
        context = create_request_context()
        user = self.admin_service.get_user(user_id, context)
        if not user:
            raise DomainError(
                      f"User with id {user_id} not found",
                      code="USER_NOT_FOUND",
                      template=N_("User with id %(id)s not found"),
                      params={"id": user_id},
                  )
        return jsonify(UserResponseSchema.from_dto(user).model_dump())

    @require_permission(SystemPermissions.ADMIN_MANAGE_USERS.value)
    def update_user_roles(self, user_id):
        """
        Handle ``PUT /api/v1/admin/users/<user_id>/roles`` – replace user roles.

        Reads JSON body with ``roles`` list.
        """
        data = request.get_json() or {}
        validated = UpdateUserRolesRequest(**data)
        context = create_request_context()
        result = self.admin_service.update_user_roles(user_id, validated.roles, context)
        return jsonify(UserResponseSchema.from_dto(result).model_dump())

    @require_permission(SystemPermissions.ADMIN_MANAGE_USERS.value)
    def confirm_user_email(self, user_id):
        """
        Handle ``POST /api/v1/admin/users/<user_id>/verify-email``.

        Marks the address as confirmed on the operator's word, for the
        cases the mailed link cannot cover: the message never arrived,
        the address is a list nobody reads, the deployment sends no mail.
        Behind ``admin:manage_users``, recorded in the log, and idempotent
        -- pressing it on an already confirmed account is not an error.
        """
        context = create_request_context()
        result = self.admin_service.confirm_user_email(user_id, context)
        return jsonify(UserResponseSchema.from_dto(result).model_dump())

    @require_permission(SystemPermissions.ADMIN_MANAGE_USERS.value)
    def resend_verification(self, user_id):
        """
        Handle ``POST /api/v1/admin/users/<user_id>/resend-verification``.

        The same use case the public endpoint runs, addressed by account
        id instead of by email: an operator acts on the account in front
        of them, and retyping the address is how mail goes to a typo.

        Answers with the address it went to. That is not a disclosure --
        the caller already reads the whole account list.
        """
        context = create_request_context()
        address = self.admin_service.resend_verification(user_id, context)
        return jsonify({"message": f"Confirmation message sent to {address}"}), 202

    @require_permission(SystemPermissions.ADMIN_MANAGE_USERS.value)
    def deactivate_user(self, user_id):
        """Handle ``POST /api/v1/admin/users/<user_id>/deactivate`` – deactivate user."""
        context = create_request_context()
        result = self.admin_service.deactivate_user(user_id, context)
        return jsonify(UserResponseSchema.from_dto(result).model_dump())

    @require_permission(SystemPermissions.ADMIN_MANAGE_USERS.value)
    def activate_user(self, user_id):
        """
        Handle ``POST /api/v1/admin/users/<user_id>/activate`` – activate user.
        """
        context = create_request_context()
        result = self.admin_service.activate_user(user_id, context)
        return jsonify(UserResponseSchema.from_dto(result).model_dump())

    @require_permission(SystemPermissions.ADMIN_MANAGE_USERS.value)
    def delete_user(self, user_id):
        """Handle ``DELETE /api/v1/admin/users/<user_id>`` – permanently delete a user."""
        context = create_request_context()
        deleted = self.admin_service.delete_user(user_id, context)
        if not deleted:
            raise DomainError(
                      f"User with id {user_id} not found",
                      code="USER_NOT_FOUND",
                      template=N_("User with id %(id)s not found"),
                      params={"id": user_id},
                  )
        return jsonify({"message": "User deleted"})

    @require_permission(SystemPermissions.ADMIN_VIEW_USERS.value)
    def get_user_stats(self, user_id):
        """Retrieve activity statistics for any user (admin only)."""
        context = create_request_context()
        stats = self.admin_service.get_user_activity_stats(user_id, context)
        return jsonify({
            "total_links": stats.total_links,
            "total_clicks": stats.total_clicks,
            "avg_clicks_per_link": stats.avg_clicks_per_link,
            "recent_links": [ShortLinkResponse.from_dto(link).model_dump() for link in stats.recent_links]
        })

    # ------------------------------------------------------------------
    # Roles
    # ------------------------------------------------------------------
    @require_permission(SystemPermissions.ADMIN_MANAGE_ROLES.value)
    def create_role(self):
        """
        Handle ``POST /api/v1/admin/roles`` – create a new role.

        Reads JSON body with ``name``, ``description``, ``permissions``.
        Returns the created role with status 201.
        """
        data = request.get_json() or {}
        validated = CreateRoleRequest(**data)
        context = create_request_context()
        result = self.admin_service.create_role(
            name=validated.name,
            description=validated.description,
            permission_names=validated.permissions,
            context=context,
        )
        return jsonify(RoleResponseSchema.from_dto(result).model_dump()), 201

    @require_permission(SystemPermissions.ADMIN_VIEW_ROLES.value)
    def list_roles(self):
        """Handle ``GET /api/v1/admin/roles`` – list all roles."""
        context = create_request_context()
        roles = self.admin_service.list_roles(context)
        return jsonify([RoleResponseSchema.from_dto(r).model_dump() for r in roles])

    @require_permission(SystemPermissions.ADMIN_VIEW_ROLES.value)
    def get_role(self, role_name):
        """
        Handle ``GET /api/v1/admin/roles/<role_name>`` – get a single role.

        Returns 404 if the role is not found.
        """
        context = create_request_context()
        role = self.admin_service.get_role(role_name, context)
        if not role:
            raise DomainError(
                      f"Role {role_name} not found",
                      code="ROLE_NOT_FOUND",
                      template=N_("Role %(name)s not found"),
                      params={"name": role_name},
                  )
        return jsonify(RoleResponseSchema.from_dto(role).model_dump())

    @require_permission(SystemPermissions.ADMIN_MANAGE_ROLES.value)
    def update_role_permissions(self, role_name):
        """
        Handle ``PUT /api/v1/admin/roles/<role_name>/permissions`` – replace role permissions.

        Reads JSON body with ``permissions`` list.
        """
        data = request.get_json() or {}
        validated = UpdateRolePermissionsRequest(**data)
        context = create_request_context()
        result = self.admin_service.update_role_permissions(
            role_name, validated.permissions, context
        )
        return jsonify(RoleResponseSchema.from_dto(result).model_dump())

    @require_permission(SystemPermissions.ADMIN_MANAGE_ROLES.value)
    def delete_role(self, role_name):
        """
        Handle ``DELETE /api/v1/admin/roles/<role_name>`` – delete a role.

        Two answers: a name that is not there is 404 ``ROLE_NOT_FOUND``,
        like the user endpoint beside it, while a role that exists and is
        protected is 400 ``ROLE_DELETION_FAILED``.
        Both are raised by the use case; the guard below is a backstop for
        a future implementation that returns ``False`` instead of raising,
        and is unreachable today.
        """
        context = create_request_context()
        deleted = self.admin_service.delete_role(role_name, context)
        if not deleted:
            raise DomainError(
                      f"Role {role_name} not found",
                      code="ROLE_NOT_FOUND",
                      template=N_("Role %(name)s not found"),
                      params={"name": role_name},
                  )
        return jsonify({"message": "Role deleted"})

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------
    @require_permission(SystemPermissions.ADMIN_VIEW_SYSTEM_HEALTH.value)
    def get_health(self):
        """Check the health of the service infrastructure."""
        context = create_request_context()
        health = self.admin_service.get_service_health(context)
        body: Dict[str, Any] = {
            "database": health.database,
            "cache": health.redis,
            "task_queue": health.task_queue,
            "rate_limiter": health.rate_limiter,
        }

        # Reported here because nothing else reports it. The counters are
        # kept by the failover service and were read by no caller, and the
        # only runtime word about which implementation holds the work is
        # one line at startup -- so an audit trail that had stopped being
        # written looked, from every surface an operator has, exactly like
        # one that was fine.
        if health.logging is not None:
            body["logging"] = {
                "logger": {
                    "active": health.logging.logger_active,
                    "dropped_calls": health.logging.logger_dropped_calls,
                    "failed_checks": health.logging.logger_failed_checks,
                    "lost_log_lines": health.logging.logger_lost_log_lines,
                },
                "audit": {
                    "active": health.logging.audit_active,
                    "dropped_calls": health.logging.audit_dropped_calls,
                    "failed_checks": health.logging.audit_failed_checks,
                    "lost_log_lines": health.logging.audit_lost_log_lines,
                },
            }

        return jsonify(body)
