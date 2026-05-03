from flask import Blueprint, render_template

from link_shortener.application import AdminService, AuthorizationService
from link_shortener.domain import SystemPermissions
from link_shortener.web.security.context import create_request_context
from link_shortener.web.security.decorators import login_required, require_permission


class AdminFrontendController:
    """
    Controller for the admin frontend (HTML pages).

    Serves Jinja templates for the admin panel, protected by login and
    permission decorators.
    """

    def __init__(self, admin_servie: AdminService, auth_service: AuthorizationService):
        self.admin_service = admin_servie
        self.auth_service = auth_service
        self.bp = Blueprint("admin_frontend", __name__, url_prefix="/admin", template_folder="../templates/admin")
        
        self._register_routes()

    def _register_routes(self):
        """Register all admin frontend routes."""
        self.bp.add_url_rule('/', view_func=self.dashboard, methods=['GET'])
        self.bp.add_url_rule('/users', view_func=self.users_list, methods=['GET'])
        self.bp.add_url_rule('/users/new', view_func=self.create_user_form, methods=['GET'])
        self.bp.add_url_rule('/users/<user_id>/edit', view_func=self.edit_user, methods=['GET'])
        self.bp.add_url_rule('/roles', view_func=self.roles_list, methods=['GET'])
        self.bp.add_url_rule('/roles/new', view_func=self.create_role_form, methods=['GET'])
        self.bp.add_url_rule('/roles/<role_name>/edit', view_func=self.edit_role, methods=['GET'])
        self.bp.add_url_rule('/login', view_func=self.login_page, methods=['GET'])

    @login_required
    @require_permission(SystemPermissions.ADMIN_VIEW_SYSTEM_HEALTH.value)
    def dashboard(self):
        """Render the admin dashboard page."""
        return render_template('admin/dashboard.html')

    @login_required
    @require_permission(SystemPermissions.ADMIN_VIEW_USERS.value)
    def users_list(self):
        """Render the list of all users."""
        context = create_request_context()
        users = self.admin_service.list_users(context)
        return render_template('admin/users_list.html', users=users)

    @login_required
    @require_permission(SystemPermissions.ADMIN_MANAGE_USERS.value)
    def create_user_form(self):
        """Render the new user creation form with available roles."""
        context = create_request_context()
        roles = self.admin_service.list_roles(context)  # для выбора ролей
        return render_template('admin/create_user.html', roles=roles)

    @login_required
    @require_permission(SystemPermissions.ADMIN_MANAGE_USERS.value)
    def edit_user(self, user_id):
        """Render the user editing form with current roles and all available roles."""
        context = create_request_context()
        user = self.admin_service.get_user(user_id, context)
        if not user:
            return render_template('error.html', error='Пользователь не найден'), 404
        all_roles = self.admin_service.list_roles(context)
        return render_template('admin/edit_user.html', user=user, all_roles=all_roles)

    @login_required
    @require_permission(SystemPermissions.ADMIN_VIEW_ROLES.value)
    def roles_list(self):
        """Render the list of all roles."""
        context = create_request_context()
        roles = self.admin_service.list_roles(context)
        return render_template('admin/roles_list.html', roles=roles)

    @login_required
    @require_permission(SystemPermissions.ADMIN_MANAGE_ROLES.value)
    def create_role_form(self):
        """Render the new role creation form with all available permissions."""
        available_permissions = SystemPermissions.all_values()
        return render_template('admin/create_role.html', permissions=available_permissions)

    @login_required
    @require_permission(SystemPermissions.ADMIN_MANAGE_ROLES.value)
    def edit_role(self, role_name):
        """Render the role editing form with current permissions and all available permissions."""
        context = create_request_context()
        role = self.admin_service.get_role(role_name, context)
        if not role:
            return render_template('error.html', error='Роль не найдена'), 404
        available_permissions = SystemPermissions.all_values()
        return render_template('admin/edit_role.html', role=role, available_permissions=available_permissions)

    def login_page(self):
        """
        Render the admin login page.

        If the user is already authenticated, the JavaScript logic will
        redirect to the dashboard.
        """
        return render_template('admin/login.html')
