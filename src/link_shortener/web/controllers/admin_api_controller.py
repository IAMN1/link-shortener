"""
Administrative API controller.

Handles endpoints for managing users, roles, viewing user statistics,
and checking service health.  All methods require the corresponding
administrative permissions.
"""

from typing import Any, Dict

from flask import Blueprint, jsonify
from link_shortener.application import AdminService
from link_shortener.application.ports.logging_status import ChainStatus
from link_shortener.application.use_cases.auth.resend_verification import (
    ResendOutcome,
)
from link_shortener.domain import (
    DomainError, RoleNotFoundError, SystemPermissions, UserNotFoundError
)
from link_shortener.web.schemas.admin.admin_request import (
    CreateRoleRequest, CreateUserRequest,
    UpdateRolePermissionsRequest, UpdateUserRolesRequest
)
from link_shortener.web.schemas.admin.admin_responses import RoleResponseSchema, UserResponseSchema
from link_shortener.web.schemas.stats import MyStatsResponse
from link_shortener.web.paging import window_from_query
from link_shortener.web.request_body import json_object
from link_shortener.web.security.context import create_request_context
from link_shortener.web.security.decorators import require_permission
from link_shortener.domain.i18n import N_


def _chain_body(chain: ChainStatus) -> Dict[str, Any]:
    """
    One failover chain, as ``GET /api/v1/admin/health`` publishes it.

    Written once for both chains. Spelled out twice, a value added to one
    and forgotten in the other reads as a chain that does not have it,
    and a name typed wrong reads as one chain's number under the other's
    heading -- which is exactly the confusion the section exists to end.

    Args:
        chain: What the component answered about itself.

    Returns:
        The section body, in the shape ``HEALTH_SCHEMA`` describes.
    """
    return {
        "active": chain.active,
        "dropped_calls": chain.dropped_calls,
        "failed_checks": chain.failed_checks,
        "lost_log_lines": chain.lost_log_lines,
        # The state no counter beside it can report. They count losses,
        # and a chain reporting itself unwell produces none while nothing
        # is being written through it: measured with `audit.log` replaced
        # by a directory on a running application, the background round
        # said "structlog_audit reports itself unhealthy" eight times in
        # ninety seconds while this body answered zero, zero, zero and an
        # unchanged `active` -- both audit implementations write the same
        # file, so there was nowhere for the work to move to.
        "last_check": chain.last_check,
    }


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
        data = json_object()
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

        Supports ``limit`` and ``offset`` query parameters, read the way
        the link listing reads them -- see ``web/paging.py`` for what
        passing them through unbounded did here. Not the way the journal
        endpoints read theirs: those refuse a window above their ceiling
        rather than trimming it, because there a trimmed window would be
        a claim about how much there is.
        """
        context = create_request_context()
        limit, offset = window_from_query(default_limit=100)
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
            raise UserNotFoundError(user_id)
        return jsonify(UserResponseSchema.from_dto(user).model_dump())

    @require_permission(SystemPermissions.ADMIN_MANAGE_USERS.value)
    def update_user_roles(self, user_id):
        """
        Handle ``PUT /api/v1/admin/users/<user_id>/roles`` – replace user roles.

        Reads JSON body with ``roles`` list.
        """
        data = json_object()
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

        Three answers, because there are three things that can happen and
        an operator acts differently on each. 202 means a message is on
        its way. 200 means there was nothing to send: the address is
        already confirmed, and the account needs no help. 503 means the
        queue would not take the message -- nothing will arrive, and that
        is a fault of the service rather than of the account.

        Unlike the public endpoint, which answers 202 to all three on
        purpose: telling them apart there would say which addresses are
        registered.
        """
        context = create_request_context()
        address, outcome = self.admin_service.resend_verification(
            user_id, context
        )

        if outcome is ResendOutcome.NOT_HANDED_OFF:
            raise DomainError(
                      f"Confirmation for {address} was not handed off",
                      code="MAIL_NOT_HANDED_OFF",
                      template=N_(
                          "Confirmation for %(email)s could not be queued"
                      ),
                      params={"email": address},
                  )

        if outcome is ResendOutcome.NOTHING_TO_SEND:
            return jsonify({
                "message": f"{address} is already confirmed; nothing to send"
            }), 200

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
            raise UserNotFoundError(user_id)
        return jsonify({"message": "User deleted"})

    @require_permission(SystemPermissions.ADMIN_VIEW_USERS.value)
    def get_user_stats(self, user_id):
        """
        Retrieve activity statistics for any user (admin only).

        The account is looked up first, as it is on every other route
        that takes an id from the address. Without that this answered
        200 with four zeroes for an id nothing carries -- the same
        answer as a real account that has never made a link -- because
        the use case takes the id as an argument and asks the link
        repository about it rather than loading the account. Measured
        against the seven neighbouring routes, which all answer 404,
        and against the panel's page for the same id, which answers 404
        as well.
        """
        context = create_request_context()
        if not self.admin_service.get_user(user_id, context):
            raise UserNotFoundError(user_id)
        stats = self.admin_service.get_user_activity_stats(user_id, context)
        return jsonify(MyStatsResponse.from_dto(stats).model_dump())

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
        data = json_object()
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
            # The domain error rather than a ``DomainError`` assembled
            # here: this sentence was written out in four places, which
            # is four msgids for one fact and four chances to disagree.
            raise RoleNotFoundError(role_name)
        return jsonify(RoleResponseSchema.from_dto(role).model_dump())

    @require_permission(SystemPermissions.ADMIN_MANAGE_ROLES.value)
    def update_role_permissions(self, role_name):
        """
        Handle ``PUT /api/v1/admin/roles/<role_name>/permissions`` – replace role permissions.

        Reads JSON body with ``permissions`` list.
        """
        data = json_object()
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
        protected is 400 ``ROLE_IS_SYSTEM``. Both are raised by the use
        case, which is why nothing is checked here: the guard that used to
        stand below tested a ``False`` the use case cannot return, and the
        chain said so in three places -- the use case returned a ``bool``
        that was always ``True``, the facade documented a ``False`` for
        "a system role or not found", and the only test of the branch
        mocked the facade into returning it.
        """
        context = create_request_context()
        self.admin_service.delete_role(role_name, context)
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
            # Beside the boolean for the same reason ``cache_configured``
            # is: "answered" and "holds our schema" are two questions, and
            # the first one alone reported healthy over a database the
            # migration had never reached.
            "database_schema": health.database_schema,
            "cache": health.redis,
            # Beside the boolean, because the boolean cannot say it: a
            # cache nobody configured answers every probe well, so
            # ``cache`` reads True on a deployment running without one
            # and the health page drew a green Redis over a service that
            # has no Redis. ``/health`` and ``flask maintenance health``
            # both told the two apart already, off this same field.
            "cache_configured": health.cache_configured,
            "task_queue_configured": health.task_queue_configured,
            "task_queue": health.task_queue,
            "rate_limiter": health.rate_limiter,
            # The verdict itself, which is what this page draws. The
            # booleans above stay: they are what was measured, and a
            # caller reading them keeps reading them. What was wrong is
            # that deciding what they mean was left to the page, a fourth
            # place spelling the same three rules -- and the one that
            # called a cache keeping entries "absent".
            "components": health.components,
            # "Did not answer in time" is not the finding "answered no"
            # is, and it names the dependency that is hanging. It reached
            # the other two surfaces and stopped here, at the one an
            # operator watches.
            "timed_out": list(health.timed_out),
        }

        # Reported here because nothing else reports it. The counters are
        # kept by the failover service and were read by no caller, and the
        # only runtime word about which implementation holds the work is
        # one line at startup -- so an audit trail that had stopped being
        # written looked, from every surface an operator has, exactly like
        # one that was fine.
        if health.logging is not None:
            body["logging"] = {
                # Whose counters these are. They live in one worker's
                # memory, a deployment runs several, and the same service
                # in the same state answered 16, 27, 28 and 6 across
                # twelve requests -- by which worker took each one.
                "worker": health.logging.worker,
                # Both chains published through one function, because
                # they publish the same five things and the copy that
                # said so twice is where a chain's counter can be sent
                # out under the other chain's name.
                "logger": _chain_body(health.logging.logger),
                "audit": _chain_body(health.logging.audit),
                # A journal whose file would not open leaves this worker
                # writing two of three, or none, and no counter above can
                # say so: nothing was dropped, because the handler that
                # would have dropped it was never built. Said with the
                # reason the operating system gave, which is what tells
                # an operator whether to fix a path or a mode.
                #
                # Both lists, because an empty failure list is also what a
                # worker writing no journals at all answers -- which
                # `LOG_TO_FILE=false` makes a supported state rather than
                # a broken one.
                "journals_written": list(health.logging.journals_written),
                "journals_unavailable": [
                    {"journal": entry.journal, "reason": entry.reason}
                    for entry in health.logging.journals_unavailable
                ],
            }

        return jsonify(body)
