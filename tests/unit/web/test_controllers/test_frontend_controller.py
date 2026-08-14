


class TestFrontend_controller:
    """Tests for the frontend (HTML) routes."""

    def test_index_get(self, client):
        """GET / returns 200 and renders index page."""
        response = client.get("/")
        assert response.status_code == 200

    def test_health_endpoint(self, client):
        """GET /health returns 200."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.get_json()["status"] == "healthy"
