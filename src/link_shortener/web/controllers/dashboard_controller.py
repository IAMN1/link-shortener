"""
Dashboard controller.

Serves HTML pages for the authenticated user's dashboard.
All pages rely on client-side JS to fetch data from the API.
"""

from flask import Blueprint, g, render_template
from link_shortener.application import LinkService, AdminService
from link_shortener.domain.system_permissions import SystemPermissions
from link_shortener.web.security.context import create_request_context
from link_shortener.web.security.decorators import login_required, require_permission


class DashboardController:

    def __init__(self, link_service: LinkService, admin_service: AdminService):
        self.link_service = link_service
        self.admin_service = admin_service
        self.bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")
        self._register_routes()

    def _register_routes(self):
        self.bp.add_url_rule("/", view_func=self.home, methods=["GET"])
        self.bp.add_url_rule("/links", view_func=self.my_links, methods=["GET"])
        self.bp.add_url_rule("/stats", view_func=self.my_stats, methods=["GET"])
        self.bp.add_url_rule("/create-link", view_func=self.create_link_form, methods=["GET"])
        self.bp.add_url_rule("/service/stats", view_func=self.service_stats, methods=["GET"])
        self.bp.add_url_rule("/service/health", view_func=self.service_health, methods=["GET"])
        self.bp.add_url_rule("/users", view_func=self.users_list, methods=["GET"])
        self.bp.add_url_rule("/users/new", view_func=self.create_user_form, methods=["GET"])
        self.bp.add_url_rule("/users/<user_id>/edit", view_func=self.edit_user, methods=["GET"])
        self.bp.add_url_rule("/users/<user_id>/stats", view_func=self.user_stats, methods=["GET"])
        self.bp.add_url_rule("/roles", view_func=self.roles_list, methods=["GET"])
        self.bp.add_url_rule("/roles/new", view_func=self.create_role_form, methods=["GET"])
        self.bp.add_url_rule("/roles/<role_name>/edit", view_func=self.edit_role, methods=["GET"])

    def _get_context(self):
        return create_request_context()

    @login_required
    def home(self):
        return render_template("dashboard/home.html")

    @login_required
    def my_links(self):
        return render_template("dashboard/my_links.html", user=g.current_user)

    @login_required
    def my_stats(self):
        return render_template("dashboard/my_stats.html")

    @login_required
    def create_link_form(self):
        return render_template("dashboard/create_link.html")

    @login_required
    @require_permission(SystemPermissions.STATS_VIEW_BASIC.value)
    def service_stats(self):
        return render_template("dashboard/service_stats.html")

    @login_required
    @require_permission(SystemPermissions.ADMIN_VIEW_SYSTEM_HEALTH.value)
    def service_health(self):
        return render_template("dashboard/health.html")

    @login_required
    @require_permission(SystemPermissions.ADMIN_VIEW_USERS.value)
    def user_stats(self, user_id):
        ctx = self._get_context()
        user = self.admin_service.get_user(user_id, ctx)
        if not user:
            return render_template("error.html", error="User not found"), 404
        return render_template("dashboard/user_stats.html", user=user)

    @login_required
    @require_permission(SystemPermissions.ADMIN_VIEW_USERS.value)
    def users_list(self):
        ctx = self._get_context()
        users = self.admin_service.list_users(ctx)
        return render_template("dashboard/users_list.html", users=users)

    @login_required
    @require_permission(SystemPermissions.ADMIN_MANAGE_USERS.value)
    def create_user_form(self):
        ctx = self._get_context()
        roles = self.admin_service.list_roles(ctx)
        return render_template("dashboard/create_user.html", roles=roles)

    @login_required
    @require_permission(SystemPermissions.ADMIN_MANAGE_USERS.value)
    def edit_user(self, user_id):
        ctx = self._get_context()
        user = self.admin_service.get_user(user_id, ctx)
        if not user:
            return render_template("error.html", error="User not found"), 404
        all_roles = self.admin_service.list_roles(ctx)
        return render_template("dashboard/edit_user.html", user=user, all_roles=all_roles)

    @login_required
    @require_permission(SystemPermissions.ADMIN_VIEW_ROLES.value)
    def roles_list(self):
        ctx = self._get_context()
        roles = self.admin_service.list_roles(ctx)
        return render_template("dashboard/roles_list.html", roles=roles)

    @login_required
    @require_permission(SystemPermissions.ADMIN_MANAGE_ROLES.value)
    def create_role_form(self):
        available_permissions = SystemPermissions.all_values()
        return render_template("dashboard/create_role.html", permissions=available_permissions)

    @login_required
    @require_permission(SystemPermissions.ADMIN_MANAGE_ROLES.value)
    def edit_role(self, role_name):
        ctx = self._get_context()
        role = self.admin_service.get_role(role_name, ctx)
        if not role:
            return render_template("error.html", error="Role not found"), 404
        available_permissions = SystemPermissions.all_values()
        return render_template(
            "dashboard/edit_role.html", role=role, available_permissions=available_permissions
        )
