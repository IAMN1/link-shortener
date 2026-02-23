from datetime import datetime


from link_shortener.application.dtos.responses import BatchCreateResponse, BatchItemResponse, ServiceStatsResponse, ShortLinkResponse, StatsItemResponse
from link_shortener.domain.exceptions import LinkNotFoundError, ValidationError as DomainValidationError

class TestApiController:
    """Tests for the REST API endpoints."""

    def test_create_short_link_success_new(self, client, mock_link_service):
        """POST /api/v1/shorten returns 201 for new link."""

        # Arrange
        expected_dto = ShortLinkResponse(
            short_code="abc123",
            short_url="http://testserver/abc123",
            original_url="https://test.com",
            clicks=0,
            created_at=datetime.now(),
            last_accessed=None,
            is_new=True,
            from_cache=False
        )
        mock_link_service.create_short_link.return_value = expected_dto

        # Act
        response = client.post(
            """/api/v1/shorten""",
            json={"url": "https://test.com"},
            headers={"X-Forwarded-For": "1.2.3.4", "User-Agent": "TestAgent"}
        )

        # Assert
        assert response.status_code == 201
        data = response.get_json()
        assert data["short_code"] == "abc123"
        mock_link_service.create_short_link.assert_called_once_with(
            "https://test.com",
            user_ip="1.2.3.4",
            user_agent="TestAgent"
        )

    def test_create_short_link_existing(self, client, mock_link_service):
        """POST /api/v1/shorten returns 200 for existing link."""
        
        # Arrange
        expected_dto = ShortLinkResponse(
            short_code="abc123",
            short_url="http://testserver/abc123",
            original_url="https://test.com",
            clicks=10,
            created_at=datetime.now(),
            last_accessed=datetime.now(),
            is_new=False,
            from_cache=True
        )
        mock_link_service.create_short_link.return_value = expected_dto

        # Act
        response = client.post(
            "/api/v1/shorten",
            json={"url": "https://test.com"},
            headers={"X-Forwarded-For": "1.2.3.4"},
        )
        
        # Assert
        assert response.status_code == 200
        data = response.get_json()
        assert data["is_new"] is False
        assert data["from_cache"] is True

    def test_create_short_link_validation_error(self, client, mock_link_service):
        """POST /api/v1/shorten returns 400 for invalid JSON (missing url)."""

        # Act
        response = client.post("/api/v1/shorten", json={})

        # Assert
        assert response.status_code == 400
        data = response.get_json()
        assert data["error"] == "VALIDATION_ERROR"
        mock_link_service.create_short_link.assert_not_called()

    def test_create_short_link_domain_validation_error(self, client, mock_link_service):
        """When service raises ValidationError, should return 400 with details."""

        # Arrange
        mock_link_service.create_short_link.side_effect = DomainValidationError(
            "Invalid URL", field="url"
        )

        # Act
        response = client.post(
            "/api/v1/shorten",
            json={"url": "invalid"},
        )

        # Assert
        assert response.status_code == 400
        data = response.get_json()
        assert data["error"] == "VALIDATION_ERROR"
        assert data["details"][0]["field"] == "url"

    def test_get_link_info_success(self, client, mock_link_service):
        """GET /api/v1/links/<code> returns link info."""

        # Arrange
        expected_dto = ShortLinkResponse(
            short_code="abc123",
            short_url="http://testserver/abc123",
            original_url="https://test.com",
            clicks=5,
            created_at=datetime.now(),
            last_accessed=datetime.now(),
            is_new=False,
            from_cache=False
        )
        mock_link_service.get_link_info.return_value = expected_dto

        # Act
        response = client.get("/api/v1/links/abc123")

        # Assert
        assert response.status_code == 200
        data = response.get_json()
        assert data["short_code"] == "abc123"
        mock_link_service.get_link_info.assert_called_once_with("abc123")

    def test_get_link_info_not_found(self, client, mock_link_service):
        """GET /api/v1/links/<code> returns 404 when link not found."""

        # Arrange
        mock_link_service.get_link_info.side_effect = LinkNotFoundError("abc123")

        # Act
        response = client.get("/api/v1/links/abc123")

        # Assert
        assert response.status_code == 404
        data = response.get_json()
        assert data["error"] == "LINK_NOT_FOUND"

    def test_batch_create_success(self, client, mock_link_service):
        """POST /api/v1/batch/shorten returns 201."""

        # Arrange
        urls = ["https://a.com", "https://b.com"]
        items = [
            BatchItemResponse.success_(
                url=urls[0],
                short_code="a1",
                original_url="https://a.com",
                base_url="http://testserver/",
                clicks=0,
                is_new=True,
                from_cache=False,
                duplicate_of=None
            ),
            BatchItemResponse.success_(
                url=urls[1],
                short_code="b1",
                original_url="https://b.com",
                base_url="http://testserver/",
                clicks=0,
                is_new=True,
                from_cache=False,
                duplicate_of=None
            )
        ]
        expected_dto = BatchCreateResponse.from_results(items)
        mock_link_service.batch_create_short_links.return_value = expected_dto

        # Act
        response = client.post(
            "/api/v1/batch/shorten",
            json={"urls": urls},
            headers={"X-Forwarded-For": "1.2.3.4", "User-Agent": "TestAgent"},
        )

        # Assert
        assert response.status_code == 201
        data = response.get_json()
        assert data["total"] == 2
        mock_link_service.batch_create_short_links.assert_called_once_with(
            urls, user_ip="1.2.3.4", user_agent="TestAgent"
        )
    
    def test_batch_create_validation_error(self, client, mock_link_service):
        """POST /api/v1/batch/shorten with invalid input returns 400."""

        # Act
        response = client.post("/api/v1/batch/shorten", json={})

        # Assert
        assert response.status_code == 400
        data = response.get_json()
        assert data["error"] == "VALIDATION_ERROR"
        mock_link_service.batch_create_short_links.assert_not_called()

    def test_get_stats(self, client, mock_link_service):
        """GET /api/v1/stats returns service stats."""

        # Arrange
        stats_items = [
            StatsItemResponse(
                short_code="abc123",
                short_url="http://testserver/abc123",
                original_url="https://test.com",
                clicks=100,
                created_at=datetime.now()
            )
        ]
        expected_dto = ServiceStatsResponse(
            total_urls=100,
            total_clicks=500,
            avg_clicks_per_url=5.0,
            popular_links=stats_items
        )
        mock_link_service.get_service_stats.return_value = expected_dto

        # Act
        response = client.get("/api/v1/stats")

        # Assert
        assert response.status_code == 200
        data = response.get_json()
        assert data["total_urls"] == 100
        mock_link_service.get_service_stats.assert_called_once()

