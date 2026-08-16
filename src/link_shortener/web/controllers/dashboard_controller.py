"""
Dashboard controller.

Serves HTML pages for the authenticated user's dashboard.
All pages rely on client-side JS to fetch data from the API.
"""

from flask import Blueprint, g, render_template, request
from flask_babel import gettext

from link_shortener.application import LinkService, AdminService
from link_shortener.domain.system_permissions import SystemPermissions
from link_shortener.infrastructure.auth.rbac_authorization_service import GUEST_ROLE_NAME
from link_shortener.web.responses import error_page
from link_shortener.web.security.context import create_request_context
from link_shortener.web.security.decorators import login_required, require_permission


USERS_PER_PAGE = 50
"""Accounts shown on one page of the user list."""


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

    # These pages are shells; their data comes from the API endpoints that
    # ask for the same permissions. Gating the page too keeps a caller who
    # will only be refused from being handed an empty screen to puzzle over.
    @login_required
    @require_permission(SystemPermissions.LINK_VIEW_OWN.value)
    def my_links(self):
        return render_template("dashboard/my_links.html", user=g.current_user)

    @login_required
    @require_permission(SystemPermissions.LINK_VIEW_OWN.value)
    def my_stats(self):
        return render_template("dashboard/my_stats.html")

    @login_required
    @require_permission(SystemPermissions.LINK_CREATE.value)
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
            return error_page("USER_NOT_FOUND", gettext("User not found"), 404)
        return render_template("dashboard/user_stats.html", user=user)

    @login_required
    @require_permission(SystemPermissions.ADMIN_VIEW_USERS.value)
    def users_list(self):
        """
        Show one page of accounts.

        The list used to render whatever ``list_users`` returns, which is
        its first hundred and no word about the rest: on a service with
        more accounts than that, the ones past the hundredth existed only
        through the API.

        One row beyond the page is asked for and not shown. It answers
        "is there a next page" without a second query, and nothing here
        counts the table -- a total would cost a scan of it on every view
        to print a number nobody navigates by.
        """
        ctx = self._get_context()
        page = max(1, request.args.get("page", 1, type=int))
        offset = (page - 1) * USERS_PER_PAGE
        found = self.admin_service.list_users(
            ctx, limit=USERS_PER_PAGE + 1, offset=offset
        )
        return render_template(
            "dashboard/users_list.html",
            users=found[:USERS_PER_PAGE],
            page=page,
            has_next=len(found) > USERS_PER_PAGE,
        )

    def _assignable_roles(self, ctx):
        """
        List the roles an operator may put on an account.

        Every role but ``guest``, which is the role an anonymous request
        acts under. Nobody holds it, and an account that does gets the
        permissions of a passer-by: the forms offered it as a choice, and
        an account made with it signs in to a dashboard it may not read.

        Args:
            ctx: Request context of the operator asking.

        Returns:
            The roles, in the order the service returned them.
        """
        return [
            role for role in self.admin_service.list_roles(ctx)
            if role.name != GUEST_ROLE_NAME
        ]

    @login_required
    @require_permission(SystemPermissions.ADMIN_MANAGE_USERS.value)
    def create_user_form(self):
        ctx = self._get_context()
        return render_template("dashboard/create_user.html", roles=self._assignable_roles(ctx))

    @login_required
    @require_permission(SystemPermissions.ADMIN_MANAGE_USERS.value)
    def edit_user(self, user_id):
        ctx = self._get_context()
        user = self.admin_service.get_user(user_id, ctx)
        if not user:
            return error_page("USER_NOT_FOUND", gettext("User not found"), 404)
        all_roles = self._assignable_roles(ctx)
        assignable = {role.name for role in all_roles}
        return render_template(
            "dashboard/edit_user.html",
            user=user,
            all_roles=all_roles,
            # Held but not offered above, so saving the form would drop it
            # without the operator ever seeing it listed.
            unassignable_held=[name for name in user.roles if name not in assignable],
        )

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
            return error_page("ROLE_NOT_FOUND", gettext("Role not found"), 404)
        if role.is_system:
            # The service refuses the save with "Cannot modify system
            # roles", so serving the form was a working-looking dead end:
            # the list hides the Edit link, and the URL behind it did not.
            return error_page(
                "FORBIDDEN",
                gettext(
                    "The role %(name)s is a system role and cannot be modified",
                    name=role.name,
                ),
                403,
            )
        available_permissions = SystemPermissions.all_values()
        return render_template(
            "dashboard/edit_role.html", role=role, available_permissions=available_permissions
        )
