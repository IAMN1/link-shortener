"""Tests for the REST API controller."""
from datetime import datetime, timezone
from unittest.mock import MagicMock

from link_shortener.application.dtos.link import ShortLinkResponse


class TestApiController:
    """Tests for the REST API endpoints."""

    def test_create_short_link_success_new(self, client, mock_link_service):
        """POST /api/v1/shorten returns 201 for new link."""
        expected_dto = ShortLinkResponse(
            short_code="abc123",
            short_url="http://testserver/abc123",
            original_url="https://test.com",
            clicks=0,
            created_at=datetime.now(timezone.utc),
            last_accessed=None,
            is_new=True,
            from_cache=False
        )
        mock_link_service.create_short_link.return_value = expected_dto

        response = client.post(
            "/api/v1/shorten",
            json={"url": "https://test.com"},
            headers={"X-Forwarded-For": "1.2.3.4", "User-Agent": "TestAgent"}
        )

        assert response.status_code == 201
        data = response.get_json()
        assert data["short_code"] == "abc123"

    def test_create_short_link_existing(self, client, mock_link_service):
        """POST /api/v1/shorten returns 200 for existing link."""
        expected_dto = ShortLinkResponse(
            short_code="abc123",
            short_url="http://testserver/abc123",
            original_url="https://test.com",
            clicks=10,
            created_at=datetime.now(timezone.utc),
            last_accessed=datetime.now(timezone.utc),
            is_new=False,
            from_cache=True
        )
        mock_link_service.create_short_link.return_value = expected_dto

        response = client.post(
            "/api/v1/shorten",
            json={"url": "https://test.com"},
            headers={"X-Forwarded-For": "1.2.3.4"},
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["is_new"] is False
        assert data["from_cache"] is True

    def test_create_short_link_with_ttl(self, client, mock_link_service):
        """POST /api/v1/shorten with ttl_seconds parameter."""
        expected_dto = ShortLinkResponse(
            short_code="abc123",
            short_url="http://testserver/abc123",
            original_url="https://test.com",
            clicks=0,
            created_at=datetime.now(timezone.utc),
            last_accessed=None,
            is_new=True,
            from_cache=False
        )
        mock_link_service.create_short_link.return_value = expected_dto

        response = client.post(
            "/api/v1/shorten",
            json={"url": "https://test.com", "ttl_seconds": 3600},
        )
        assert response.status_code == 201

    def test_create_short_link_validation_error(self, client, mock_link_service):
        """POST /api/v1/shorten returns 400 for invalid JSON."""
        response = client.post("/api/v1/shorten", json={})
        assert response.status_code == 400
        data = response.get_json()
        assert data["error"] == "VALIDATION_ERROR"
        mock_link_service.create_short_link.assert_not_called()

    def test_get_link_info_success(self, client, mock_link_service):
        """GET /api/v1/links/<code> returns link info."""
        expected_dto = ShortLinkResponse(
            short_code="abc123",
            short_url="http://testserver/abc123",
            original_url="https://test.com",
            clicks=5,
            created_at=datetime.now(timezone.utc),
            last_accessed=datetime.now(timezone.utc),
            is_new=False,
            from_cache=False
        )
        mock_link_service.get_link_info.return_value = expected_dto

        response = client.get("/api/v1/links/abc123")
        assert response.status_code == 200
        data = response.get_json()
        assert data["short_code"] == "abc123"

    def test_get_extended_link_info_refuses_anonymous(
        self, client, mock_link_service
    ):
        """GET /api/v1/links/<code>/extended is not public."""
        expected_dto = MagicMock()
        expected_dto.owner_id = "user-1"
        mock_link_service.get_extended_link_info.return_value = expected_dto

        response = client.get("/api/v1/links/abc123/extended")

        # 401, not 403: nobody is logged in, and the two answers mean
        # different things to a client.
        assert response.status_code == 401
        # The entitled paths are covered against a real authorization
        # service in tests/integration/web/controllers/test_link_access.py:
        # the service is a bare Mock here, so every permission check in
        # this module passes regardless of what the code asks for.

    def test_batch_create_success(self, client, mock_link_service):
        """POST /api/v1/batch/shorten creates multiple links."""
        batch_response = MagicMock()
        batch_response.model_dump.return_value = {
            "results": [
                {
                    "success": True,
                    "url": "https://a.com",
                    "short_code": "abc123",
                    "short_url": "http://testserver/abc123",
                    "original_url": "https://a.com",
                    "is_new": True,
                }
            ]
        }
        mock_link_service.batch_create_short_links.return_value = batch_response

        response = client.post(
            "/api/v1/batch/shorten",
            json={"urls": ["https://a.com"]},
        )
        assert response.status_code == 200

    def test_batch_create_validation_error(self, client, mock_link_service):
        """POST /api/v1/batch/shorten with invalid input returns 400."""
        response = client.post("/api/v1/batch/shorten", json={})
        assert response.status_code == 400
        data = response.get_json()
        assert data["error"] == "VALIDATION_ERROR"

    def test_get_stats(self, client, mock_link_service):
        """GET /api/v1/stats returns service stats."""
        stats_dto = MagicMock()
        stats_dto.model_dump.return_value = {
            "total_urls": 100,
            "total_clicks": 500,
            "avg_clicks_per_url": 5.0,
            "popular_links": [],
        }
        mock_link_service.get_service_stats.return_value = stats_dto

        response = client.get("/api/v1/stats")
        assert response.status_code == 200

    def test_get_my_links_returns_401_when_unauthenticated(self, client, mock_link_service):
        """GET /api/v1/links/mine returns 401 when not authenticated."""
        response = client.get("/api/v1/links/mine")
        assert response.status_code == 401

    def test_get_my_links_with_pagination_returns_401_when_unauthenticated(self, client, mock_link_service):
        """GET /api/v1/links/mine with params returns 401 when not authenticated."""
        response = client.get("/api/v1/links/mine?offset=10&limit=25")
        assert response.status_code == 401
