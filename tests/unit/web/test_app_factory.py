
from link_shortener.web.app_factory import create_app
from link_shortener.web.dependency_injection import Container


class Test_app_factory:
    """Tests for the app_factory"""

    def test_create_app_development(self, monkeypatch):
        """
        App factory creates app with development config 
            when FLASK_ENV=development
        """

        # Arrange
        # Подменяем get_link_service, чтобы избежать реальных зависимостей
        def mock_get_link_service(self):
            from unittest.mock import Mock
            return Mock()

        monkeypatch.setattr(Container, "get_link_service", mock_get_link_service)

        monkeypatch.setenv("FLASK_ENV", "development")
        # Удалим переменные, которые могут мешать (если они заданы)
        monkeypatch.delenv("SECRET_KEY", raising=False)
        monkeypatch.delenv("SHORT_CODE_PEPPER", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("REDIS_URL", raising=False)

        # Act
        app = create_app()

        # Assert
        assert app is not None
        assert app.testing is False
        assert app.debug is True  # development config has DEBUG=True

    def test_create_app_with_config(self, test_config):
        """App factory accepts custom config dict."""

        # Act
        app = create_app(test_config)

        # Assert
        assert app.config["TESTING"] is True
        assert app.config["DEBUG"] is False

    def test_health_endpoint(self, client):
        """GET /health returns 200 with JSON status."""

        # Act
        response = client.get("/health")

        # Assert
        assert response.status_code == 200
        assert response.get_json() == {"status": "healthy"}

    def test_redirect_endpoint(self, client, mock_link_service):
        """GET /<short_code> redirects to original URL."""

        # Arrange
        mock_link_service.redirect.return_value = "https://test.com"

        # Act
        response = client.get("/abc123", headers={"X-Forwarded-For": "1.2.3.4"})

        # Assert
        assert response.status_code == 302
        assert response.location == "https://test.com"
        mock_link_service.redirect.assert_called_once_with(
            "abc123", user_ip="1.2.3.4", user_agent=None
        )

    def test_teardown_context_registered(self, app):
        """App teardown function should be registered."""

        # Act & Assert
        assert app.teardown_appcontext_funcs
