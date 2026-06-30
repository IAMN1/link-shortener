from unittest.mock import Mock, patch
from link_shortener.web.app_factory import create_app
from link_shortener.infrastructure.di.container import Container


class Test_app_factory:
    """Tests for the app_factory"""

    def test_create_app_with_config(self, test_config):
        """App factory accepts custom config object."""

        # Act
        app = create_app(test_config)

        # Assert
        assert app is not None
        assert app.config["TESTING"] is True
        assert app.config["DEBUG"] is False

    def test_health_endpoint(self, client):
        """GET /health returns 200 with JSON status."""

        # Act
        response = client.get("/health")

        # Assert
        assert response.status_code == 200
        assert response.get_json() == {"status": "healthy"}

    def test_teardown_context_registered(self, app):
        """App should have a container attribute."""
        assert hasattr(app, 'container')
