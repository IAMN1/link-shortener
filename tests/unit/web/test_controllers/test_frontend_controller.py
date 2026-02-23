from datetime import datetime

from link_shortener.application.dtos.responses import ShortLinkResponse
from link_shortener.domain.exceptions import LinkNotFoundError



class TestFrontend_controller:
    """Tests for the frontend (HTML) routes."""

    def test_index_get(self, client):
        """GET / returns 200 and renders index.html."""
        response = client.get("/")
        assert response.status_code == 200
        assert b"Rendered index.html" in response.data
    
    def test_shorten_post_success(self, client, mock_link_service):
        """POST /shorten with valid URL redirects to info page."""
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

        response = client.post(
            "/shorten",
            data={"url": "https://test.com"},
            headers={"X-Forwarded-For": "1.2.3.4", "User-Agent": "TestAgent"}
        )

        assert response.status_code == 302
        assert response.location == "/info/abc123"
        mock_link_service.create_short_link.assert_called_once_with(
            "https://test.com", user_ip="1.2.3.4", user_agent="TestAgent"
        )
    
    def test_shorten_post_no_url(self, client, mock_link_service):
        """POST /shorten with empty URL returns 400."""
        response = client.post("/shorten", data={})
        assert response.status_code == 400
        assert b"Rendered error.html" in response.data
        mock_link_service.create_short_link.assert_not_called()

    def test_shorten_post_exception(self, client, mock_link_service):
        """POST /shorten when service raises exception returns 500."""
        mock_link_service.create_short_link.side_effect = Exception("Boom")

        response = client.post("/shorten", data={"url": "https://test.com"})
        assert response.status_code == 500
        assert b"Rendered error.html" in response.data

    def test_info_get_success(self, client, mock_link_service):
        """GET /info/<code> returns info page with link details."""
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

        response = client.get("/info/abc123")
        assert response.status_code == 200
        assert b"Rendered info.html" in response.data

    def test_info_get_not_found(self, client, mock_link_service):
        """GET /info/<code> when link not found returns 404."""
        mock_link_service.get_link_info.side_effect = LinkNotFoundError("abc123")

        response = client.get("/info/abc123")
        assert response.status_code == 404
        assert b"Rendered error.html" in response.data

    def test_info_get_exception(self, client, mock_link_service):
        """GET /info/<code> when service raises exception returns 500."""
        mock_link_service.get_link_info.side_effect = Exception("Boom")

        response = client.get("/info/abc123")
        assert response.status_code == 500
        assert b"Rendered error.html" in response.data