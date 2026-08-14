"""Tests for the dashboard controller."""


class TestDashboardController:
    """Tests for DashboardController endpoints."""

    def test_home_redirects_when_unauthenticated(self, client):
        """GET /dashboard/ redirects to login when not authenticated."""
        response = client.get("/dashboard/")
        assert response.status_code == 302

    def test_my_links_redirects_when_unauthenticated(self, client):
        """GET /dashboard/links redirects to login when not authenticated."""
        response = client.get("/dashboard/links")
        assert response.status_code == 302

    def test_my_stats_redirects_when_unauthenticated(self, client):
        """GET /dashboard/stats redirects to login when not authenticated."""
        response = client.get("/dashboard/stats")
        assert response.status_code == 302

    def test_create_link_form_redirects_when_unauthenticated(self, client):
        """GET /dashboard/create-link redirects to login when not authenticated."""
        response = client.get("/dashboard/create-link")
        assert response.status_code == 302

    def test_service_stats_redirects_when_unauthenticated(self, client):
        """GET /dashboard/service/stats redirects to login when not authenticated."""
        response = client.get("/dashboard/service/stats")
        assert response.status_code == 302

    def test_service_health_redirects_when_unauthenticated(self, client):
        """GET /dashboard/service/health redirects to login when not authenticated."""
        response = client.get("/dashboard/service/health")
        assert response.status_code == 302

    def test_users_list_redirects_when_unauthenticated(self, client):
        """GET /dashboard/users redirects to login when not authenticated."""
        response = client.get("/dashboard/users")
        assert response.status_code == 302

    def test_create_user_form_redirects_when_unauthenticated(self, client):
        """GET /dashboard/users/new redirects to login when not authenticated."""
        response = client.get("/dashboard/users/new")
        assert response.status_code == 302

    def test_roles_list_redirects_when_unauthenticated(self, client):
        """GET /dashboard/roles redirects to login when not authenticated."""
        response = client.get("/dashboard/roles")
        assert response.status_code == 302

    def test_create_role_form_redirects_when_unauthenticated(self, client):
        """GET /dashboard/roles/new redirects to login when not authenticated."""
        response = client.get("/dashboard/roles/new")
        assert response.status_code == 302

    def test_edit_role_redirects_when_unauthenticated(self, client):
        """GET /dashboard/roles/<name>/edit redirects to login when not authenticated."""
        response = client.get("/dashboard/roles/admin/edit")
        assert response.status_code == 302

    def test_edit_role_not_found_redirects_when_unauthenticated(self, client):
        """GET /dashboard/roles/<name>/edit redirects when not authenticated."""
        response = client.get("/dashboard/roles/unknown/edit")
        assert response.status_code == 302
