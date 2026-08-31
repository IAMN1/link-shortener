"""Tests for the admin API controller."""
from unittest.mock import MagicMock

from link_shortener.application.ports.logging_status import (
    ChainStatus, LoggingStatus,
)
from link_shortener.domain import RoleNotFoundError


def _get_admin_controller(app):
    """Extract the AdminApiController instance from the registered blueprints."""
    for view in app.view_functions.values():
        if hasattr(view, '__self__') and view.__self__.__class__.__name__ == 'AdminApiController':
            return view.__self__
    return None


class TestAdminApiController:
    """Tests for AdminApiController endpoints."""

    def test_list_users(self, app, client):
        """GET /api/v1/admin/users returns user list."""
        ctrl = _get_admin_controller(app)
        ctrl.admin_service.list_users.return_value = []

        response = client.get("/api/v1/admin/users")
        assert response.status_code == 200

    def test_create_user(self, app, client):
        """POST /api/v1/admin/users creates a user."""
        ctrl = _get_admin_controller(app)
        mock_user = MagicMock()
        mock_user.id = "u1"
        mock_user.email = "admin@test.com"
        mock_user.roles = ["admin"]
        mock_user.is_active = True
        ctrl.admin_service.create_user.return_value = mock_user

        response = client.post(
            "/api/v1/admin/users",
            # Past the floor of eight: the schema takes that floor from the
            # domain policy, which is what actually refuses a weaker one.
            json={
                "email": "admin@test.com",
                "password": "a-password-of-their-own",
                "roles": ["admin"],
            },
        )
        assert response.status_code == 201

    def test_get_user(self, app, client):
        """GET /api/v1/admin/users/<id> returns user data."""
        ctrl = _get_admin_controller(app)
        mock_user = MagicMock()
        mock_user.id = "u1"
        mock_user.email = "test@test.com"
        mock_user.roles = ["user"]
        mock_user.is_active = True
        ctrl.admin_service.get_user.return_value = mock_user

        response = client.get("/api/v1/admin/users/u1")
        assert response.status_code == 200

    def test_get_user_not_found(self, app, client):
        """GET /api/v1/admin/users/<id> returns 404 when not found."""
        ctrl = _get_admin_controller(app)
        ctrl.admin_service.get_user.return_value = None

        response = client.get("/api/v1/admin/users/unknown")
        assert response.status_code == 404

    def test_update_user_roles(self, app, client):
        """PUT /api/v1/admin/users/<id>/roles updates roles."""
        ctrl = _get_admin_controller(app)
        mock_user = MagicMock()
        mock_user.id = "u1"
        mock_user.email = "test@test.com"
        mock_user.roles = ["admin"]
        mock_user.is_active = True
        ctrl.admin_service.update_user_roles.return_value = mock_user

        response = client.put(
            "/api/v1/admin/users/u1/roles",
            json={"roles": ["admin"]},
        )
        assert response.status_code == 200

    def test_deactivate_user(self, app, client):
        """POST /api/v1/admin/users/<id>/deactivate deactivates user."""
        ctrl = _get_admin_controller(app)
        mock_user = MagicMock()
        mock_user.id = "u1"
        mock_user.email = "test@test.com"
        mock_user.roles = ["user"]
        mock_user.is_active = False
        ctrl.admin_service.deactivate_user.return_value = mock_user

        response = client.post("/api/v1/admin/users/u1/deactivate")
        assert response.status_code == 200

    def test_activate_user(self, app, client):
        """POST /api/v1/admin/users/<id>/activate activates user."""
        ctrl = _get_admin_controller(app)
        mock_user = MagicMock()
        mock_user.id = "u1"
        mock_user.email = "test@test.com"
        mock_user.roles = ["user"]
        mock_user.is_active = True
        ctrl.admin_service.activate_user.return_value = mock_user

        response = client.post("/api/v1/admin/users/u1/activate")
        assert response.status_code == 200

    def test_delete_user(self, app, client):
        """DELETE /api/v1/admin/users/<id> deletes user."""
        ctrl = _get_admin_controller(app)
        ctrl.admin_service.delete_user.return_value = True

        response = client.delete("/api/v1/admin/users/u1")
        assert response.status_code == 200

    def test_delete_user_not_found(self, app, client):
        """DELETE /api/v1/admin/users/<id> returns 404 when not found."""
        ctrl = _get_admin_controller(app)
        ctrl.admin_service.delete_user.return_value = False

        response = client.delete("/api/v1/admin/users/unknown")
        assert response.status_code == 404

    def test_list_roles(self, app, client):
        """GET /api/v1/admin/roles returns role list."""
        ctrl = _get_admin_controller(app)
        ctrl.admin_service.list_roles.return_value = []

        response = client.get("/api/v1/admin/roles")
        assert response.status_code == 200

    def _make_role_mock(self, name="editor", description="Editor role", is_system=False):
        """Create a mock role with all required attributes for schema serialization."""
        mock_role = MagicMock()
        mock_role.id = f"role-{name}"
        mock_role.name = name
        mock_role.description = description
        mock_role.is_system = is_system
        perm = MagicMock()
        perm.id = "perm-1"
        perm.name = "link:create"
        perm.resource = "link"
        perm.action = "create"
        perm.description = "Create link"
        mock_role.permissions = [perm]
        return mock_role

    def test_create_role(self, app, client):
        """POST /api/v1/admin/roles creates a role."""
        ctrl = _get_admin_controller(app)
        ctrl.admin_service.create_role.return_value = self._make_role_mock()

        response = client.post(
            "/api/v1/admin/roles",
            json={"name": "editor", "description": "Editor role", "permissions": ["link:create"]},
        )
        assert response.status_code == 201

    def test_get_role(self, app, client):
        """GET /api/v1/admin/roles/<name> returns role data."""
        ctrl = _get_admin_controller(app)
        ctrl.admin_service.get_role.return_value = self._make_role_mock(name="admin")

        response = client.get("/api/v1/admin/roles/admin")
        assert response.status_code == 200

    def test_get_role_not_found(self, app, client):
        """GET /api/v1/admin/roles/<name> returns 404 when not found."""
        ctrl = _get_admin_controller(app)
        ctrl.admin_service.get_role.return_value = None

        response = client.get("/api/v1/admin/roles/unknown")
        assert response.status_code == 404

    def test_update_role_permissions(self, app, client):
        """PUT /api/v1/admin/roles/<name>/permissions updates permissions."""
        ctrl = _get_admin_controller(app)
        ctrl.admin_service.update_role_permissions.return_value = self._make_role_mock(name="editor")

        response = client.put(
            "/api/v1/admin/roles/editor/permissions",
            json={"permissions": ["link:create"]},
        )
        assert response.status_code == 200

    def test_delete_role(self, app, client):
        """DELETE /api/v1/admin/roles/<name> deletes role."""
        ctrl = _get_admin_controller(app)
        ctrl.admin_service.delete_role.return_value = None

        response = client.delete("/api/v1/admin/roles/editor")
        assert response.status_code == 200

    def test_delete_role_not_found(self, app, client):
        """A name nothing carries is 404, and the use case says so.

        This used to mock the facade into returning ``False`` and assert
        that the route noticed -- a branch the use case cannot reach,
        since it raises. What the route actually answers is whatever the
        refusal's code maps to.
        """
        ctrl = _get_admin_controller(app)
        ctrl.admin_service.delete_role.side_effect = RoleNotFoundError(
            "system"
        )

        response = client.delete("/api/v1/admin/roles/system")
        assert response.status_code == 404
        assert response.get_json()["error"] == "ROLE_NOT_FOUND"

    def test_get_health(self, app, client):
        """GET /api/v1/admin/health returns health status."""
        ctrl = _get_admin_controller(app)
        mock_health = MagicMock()
        mock_health.database = True
        # A MagicMock attribute is not a boolean and does not survive jsonify:
        # left unset, the endpoint answered 500 rather than reporting a schema.
        mock_health.database_schema = True
        mock_health.redis = True
        mock_health.task_queue = True
        mock_health.rate_limiter = True
        mock_health.cache_configured = True
        mock_health.task_queue_configured = True
        mock_health.timed_out = ()
        mock_health.logging = LoggingStatus(
            worker=4242,
            logger=ChainStatus("structlog", 0, 0, 4, "healthy"),
            audit=ChainStatus("structlog_audit", 2, 1, 0, "unhealthy"),
            journals_written=("application",),
            journals_unavailable=(),
        )
        ctrl.admin_service.get_service_health.return_value = mock_health

        response = client.get("/api/v1/admin/health")
        assert response.status_code == 200
        data = response.get_json()
        assert data["database"] is True
        # The admin panel reports the same components the container probe
        # does, from the same snapshot -- plus the logging chains, which
        # nothing else reports at all.
        assert set(data) == {
            "database", "database_schema", "cache", "cache_configured",
            "task_queue", "task_queue_configured", "rate_limiter",
            "timed_out", "logging"
        }
        assert data["logging"]["audit"]["dropped_calls"] == 2
        assert data["logging"]["audit"]["failed_checks"] == 1
        assert data["logging"]["audit"]["lost_log_lines"] == 0
        assert data["logging"]["logger"]["active"] == "structlog"
        # Distinct from the audit chain's, so that a body reporting one
        # chain's count under both names does not read as correct.
        assert data["logging"]["logger"]["lost_log_lines"] == 4

    def test_get_health_without_a_logging_reader(self, app, client):
        """The section is omitted rather than reported as zeroes.

        A use case built without the reader -- which is every caller that
        predates it -- would otherwise publish counters of zero, and zero
        reads as "nothing was lost" rather than as "nobody looked".
        """
        ctrl = _get_admin_controller(app)
        mock_health = MagicMock()
        mock_health.database = True
        # A MagicMock attribute is not a boolean and does not survive jsonify:
        # left unset, the endpoint answered 500 rather than reporting a schema.
        mock_health.database_schema = True
        mock_health.redis = True
        mock_health.task_queue = True
        mock_health.rate_limiter = True
        mock_health.cache_configured = True
        mock_health.task_queue_configured = True
        mock_health.timed_out = ()
        mock_health.logging = None
        ctrl.admin_service.get_service_health.return_value = mock_health

        response = client.get("/api/v1/admin/health")

        # The status first: publishing the section unconditionally raises
        # on the None and the caller gets a 500 whose body has no
        # "logging" key either -- so the assertion below would pass on the
        # error envelope. `if health.logging is not None:` widened to
        # `if True:` leaves the rest of this file green.
        assert response.status_code == 200
        assert "logging" not in response.get_json()

    def test_list_users_passes_the_window_it_was_asked_for(self, app, client):
        """``limit`` and ``offset`` can be swapped and nothing notices.

        Passing ``limit=offset`` and ``offset=limit`` answers 200 with an
        empty list, because every other test that reaches this endpoint
        sets the service to answer ``[]``
        and none looked at what it had been asked for.
        """
        ctrl = _get_admin_controller(app)
        ctrl.admin_service.list_users.return_value = []

        client.get("/api/v1/admin/users?limit=7&offset=3")

        _args, kwargs = ctrl.admin_service.list_users.call_args
        assert kwargs["limit"] == 7
        assert kwargs["offset"] == 3

    def test_list_users_has_a_window_when_none_was_asked_for(self, app, client):
        """A caller naming neither must not get the whole table."""
        ctrl = _get_admin_controller(app)
        ctrl.admin_service.list_users.return_value = []

        client.get("/api/v1/admin/users")

        _args, kwargs = ctrl.admin_service.list_users.call_args
        assert kwargs["limit"] == 100
        assert kwargs["offset"] == 0

    def test_list_users_answers_with_the_users_it_was_given(self, app, client):
        """The body was never read, so a list built from nothing passed."""
        ctrl = _get_admin_controller(app)
        first, second = MagicMock(), MagicMock()
        first.id, first.email = "u1", "first@test.com"
        first.roles, first.is_active = ["user"], True
        second.id, second.email = "u2", "second@test.com"
        second.roles, second.is_active = ["admin"], False
        ctrl.admin_service.list_users.return_value = [first, second]

        data = client.get("/api/v1/admin/users").get_json()

        assert [user["email"] for user in data] == [
            "first@test.com", "second@test.com"
        ]
        assert [user["is_active"] for user in data] == [True, False]

    def test_get_user_stats(self, app, client):
        """GET /api/v1/admin/users/<id>/stats returns user stats."""
        ctrl = _get_admin_controller(app)
        mock_stats = MagicMock()
        mock_stats.total_links = 10
        mock_stats.total_clicks = 50
        mock_stats.avg_clicks_per_link = 5.0
        mock_stats.recent_links = []
        ctrl.admin_service.get_user_activity_stats.return_value = mock_stats

        response = client.get("/api/v1/admin/users/u1/stats")
        assert response.status_code == 200
        data = response.get_json()
        assert data["total_links"] == 10
