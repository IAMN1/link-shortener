from link_shortener.domain.exceptions import DomainError, LinkNotFoundError, ValidationError as DomainValidationError


class TestErrorHandlerMiddleware:
    """Tests for the centralized error handling middleware."""

    def test_404_html(self, client, mock_link_service):
        """Request to non-existent HTML route returns 404 page."""

        # Arrange
        mock_link_service.redirect.side_effect = LinkNotFoundError("nonexistent")

        # Act
        response = client.get("/nonexistent", headers={"Accept": "text/html"})

        # Assert
        assert response.status_code == 404
        assert b"Rendered error.html" in response.data

    def test_404_json(self, client):
        """Request to non-existent API route returns JSON error."""

        # Act
        response = client.get("/api/v1/nonexistent", headers={"Accept": "application/json"})

        # Assert
        assert response.status_code == 404
        data = response.get_json()
        assert data["error"] == "NOT_FOUND"

    def test_405_json(self, client):
        """POST to GET-only API route returns 405 JSON."""

        # Act
        response = client.post("/api/v1/stats")

        # Assert
        assert response.status_code == 405
        data = response.get_json()
        assert data["error"] == "METHOD_NOT_ALLOWED"

    def test_405_html(self, client):
        """POST to GET-only HTML route should return 405 HTML page."""

        # Act
        response = client.post("/", headers={"Accept": "text/html"})

        # Assert
        assert response.status_code == 405
        assert b"Rendered error.html" in response.data

    def test_pydantic_validation_error(self, client):
        """POST /api/v1/shorten with invalid data type returns 400 JSON."""

        # Act
        response = client.post("/api/v1/shorten", json={"url": 123})
        
        # Assert
        assert response.status_code == 400
        data = response.get_json()
        assert data["error"] == "VALIDATION_ERROR"
        assert "details" in data

    def test_domain_validation_error(self, client, mock_link_service):
        """Domain ValidationError should return 400 JSON."""

        # Arrange
        mock_link_service.create_short_link.side_effect = DomainValidationError(
            "Invalid URL", field="url"
        )

        # Act
        response = client.post("/api/v1/shorten", json={"url": "bad"})

        # Assert
        assert response.status_code == 400
        data = response.get_json()
        assert data["error"] == "VALIDATION_ERROR"
        assert data["details"][0]["field"] == "url"

    def test_domain_error(self, client, mock_link_service):
        """DomainError should return 400 JSON."""

        # Arrange
        mock_link_service.create_short_link.side_effect = DomainError("Test domain error")

        # Act
        response = client.post("/api/v1/shorten", json={"url": "https://test.com"})

        # Assert
        assert response.status_code == 400
        data = response.get_json()
        assert data["error"] == "DOMAIN_ERROR"

    def test_value_error(self, client, mock_link_service):
        """ValueError should return 400 JSON."""

        # Arrange
        mock_link_service.create_short_link.side_effect = ValueError("Some value error")

        # Act
        response = client.post("/api/v1/shorten", json={"url": "https://test.com"})

        # Assert
        assert response.status_code == 400
        data = response.get_json()
        assert data["error"] == "VALUE_ERROR"

    def test_link_not_found_error(self, client, mock_link_service):
        """LinkNotFoundError should return 404 JSON."""

        # Arrange
        mock_link_service.get_link_info.side_effect = LinkNotFoundError("abc123")

        # Act
        response = client.get("/api/v1/links/abc123")

        # Assert
        assert response.status_code == 404
        data = response.get_json()
        assert data["error"] == "LINK_NOT_FOUND"

    def test_generic_exception_html(self, client, mock_link_service):
        """Unhandled exception in HTML route returns 500 page."""

        # Arrange
        mock_link_service.create_short_link.side_effect = Exception("Boom")

        # Act
        response = client.post("/api/v1/shorten", json={"url": "https://test.com"})

        # Assert
        assert response.status_code == 500

    def test_generic_exception_json(self, client, mock_link_service):
        """Unhandled exception in API route returns 500 JSON."""
        mock_link_service.create_short_link.side_effect = Exception("Boom")

        response = client.post("/api/v1/shorten", json={"url": "https://test.com"})
        assert response.status_code == 500
        data = response.get_json()
        assert data["error"] == "INTERNAL_SERVER_ERROR"

    def test_malformed_json_returns_400(self, client):
        """POST with invalid JSON body returns 400, not 500."""
        response = client.post(
            "/api/v1/shorten",
            data="not json",
            content_type="application/json",
        )
        assert response.status_code == 400
        data = response.get_json()
        assert data["error"] == "BAD_REQUEST"