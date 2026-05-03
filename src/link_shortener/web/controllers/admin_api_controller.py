from flask import Blueprint, jsonify, request

from link_shortener.application import AdminService
from link_shortener.domain import SystemPermissions
from link_shortener.web.schemas.admin.admin_request import CreateRoleRequest, CreateUserRequest, UpdateRolePermissionsRequest, UpdateUserRolesRequest
from link_shortener.web.schemas.admin.admin_responses import RoleResponseSchema, UserResponseSchema
from link_shortener.web.security.context import create_request_context
from link_shortener.web.security.decorators import require_permission


class AdminApiController:
    """
    RESTful controller for administrative operations.

    Exposes endpoints for managing users and roles under ``/api/v1/admin``.
    All endpoints require appropriate permissions (checked by decorators).
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
        self.bp.add_url_rule("/users/<user_id>/deactivate", view_func=self.deactivate_user, methods=["POST"])
        self.bp.add_url_rule("/users/<user_id>/activate", view_func=self.activate_user, methods=["POST"])
        self.bp.add_url_rule("/users/<user_id>", view_func=self.delete_user, methods=["DELETE"])

        # Roles
        self.bp.add_url_rule("/roles", view_func=self.create_role, methods=["POST"])
        self.bp.add_url_rule("/roles", view_func=self.list_roles, methods=["GET"])
        self.bp.add_url_rule("/roles/<role_name>", view_func=self.get_role, methods=["GET"])
        self.bp.add_url_rule("/roles/<role_name>/permissions", view_func=self.update_role_permissions, methods=["PUT"])
        self.bp.add_url_rule("/roles/<role_name>", view_func=self.delete_role, methods=["DELETE"])


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
        data = request.get_json()
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
            return jsonify({"error": "User not found"}), 404
        return jsonify(UserResponseSchema.from_dto(user).model_dump())

    @require_permission(SystemPermissions.ADMIN_MANAGE_USERS.value)
    def update_user_roles(self, user_id):
        """
        Handle ``PUT /api/v1/admin/users/<user_id>/roles`` – replace user roles.

        Reads JSON body with ``roles`` list.
        """
        data = request.get_json()
        validated = UpdateUserRolesRequest(**data)
        context = create_request_context()
        result = self.admin_service.update_user_roles(user_id, validated.roles, context)
        return jsonify(UserResponseSchema.from_dto(result).model_dump())

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
            return jsonify({"error": "User not found"}), 404
        return jsonify({"message": "User deleted"})


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
        data = request.get_json()
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
            return jsonify({"error": "Role not found"}), 404
        return jsonify(RoleResponseSchema.from_dto(role).model_dump())

    @require_permission(SystemPermissions.ADMIN_MANAGE_ROLES.value)
    def update_role_permissions(self, role_name):
        """
        Handle ``PUT /api/v1/admin/roles/<role_name>/permissions`` – replace role permissions.

        Reads JSON body with ``permissions`` list.
        """
        data = request.get_json()
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

        Returns 404 if the role is system or does not exist.
        """
        context = create_request_context()
        deleted = self.admin_service.delete_role(role_name, context)
        if not deleted:
            return jsonify({"error": "Role not found or is system"}), 404
        return jsonify({"message": "Role deleted"})
