"""Tests for the admin API controller."""
from unittest.mock import MagicMock, Mock


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
            json={"email": "admin@test.com", "password": "pass123", "roles": ["admin"]},
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
        ctrl.admin_service.delete_role.return_value = True

        response = client.delete("/api/v1/admin/roles/editor")
        assert response.status_code == 200

    def test_delete_role_not_found(self, app, client):
        """DELETE /api/v1/admin/roles/<name> returns 404 when not found."""
        ctrl = _get_admin_controller(app)
        ctrl.admin_service.delete_role.return_value = False

        response = client.delete("/api/v1/admin/roles/system")
        assert response.status_code == 404

    def test_get_health(self, app, client):
        """GET /api/v1/admin/health returns health status."""
        ctrl = _get_admin_controller(app)
        mock_health = MagicMock()
        mock_health.database = True
        mock_health.redis = True
        mock_health.task_queue = True
        ctrl.admin_service.get_service_health.return_value = mock_health

        response = client.get("/api/v1/admin/health")
        assert response.status_code == 200
        data = response.get_json()
        assert data["database"] is True

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
