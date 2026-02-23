from datetime import datetime
from pydantic import ValidationError as PydanticValidationError
from link_shortener.web.schemas.requests import BatchCreateLinkRequest, CreateShortLinkRequest
from link_shortener.web.schemas.responses import BatchItemResponse, ErrorDetail, ErrorResponse, ShortLinkResponse
import pytest


# ------------------------------------------------------------------
# Requests
# ------------------------------------------------------------------
class TestRequestSchemas:
    def test_create_short_link_request_valid(self):
        data = {"url": "https://test.com"}
        req = CreateShortLinkRequest(**data)
        assert req.url == "https://test.com"

    def test_create_short_link_request_accepts_any_string(self):
        req = CreateShortLinkRequest(url="invalid")
        assert req.url == "invalid"

    def test_batch_create_link_request_valid(self):
        data = {"urls": ["https://a.com", "https://b.com"]}
        req = BatchCreateLinkRequest(**data)
        assert len(req.urls) == 2

    def test_batch_create_link_request_too_many(self):
        urls = ["https://a.com"] * 101
        with pytest.raises(PydanticValidationError, match="too_long"):
            BatchCreateLinkRequest(urls=urls)


# ------------------------------------------------------------------
# Response
# ------------------------------------------------------------------
class TestResponseSchemas:
    def test_short_link_response_from_dto(self):
        class MockDTO:
            short_code = "abc123"
            short_url = "http://test/abc123"
            original_url = "https://test.com"
            clicks = 10
            created_at = datetime(2026, 2, 21)
            last_accessed = datetime(2026, 2, 21)
            is_new = False
            from_cache = True

        response = ShortLinkResponse.from_dto(MockDTO())
        assert response.short_code == "abc123"
        assert response.clicks == 10

    def test_batch_item_response_from_dto(self):
        class MockDTO:
            success = True
            url = "https://test.com"
            short_code = "abc123"
            short_url = "http://test/abc123"
            error = None
            is_new = False
            from_cache = True
            duplicate_of = None

        item = BatchItemResponse.from_dto(MockDTO())
        assert item.success is True
        assert item.short_code == "abc123"

    def test_error_response_serialization(self):
        error = ErrorResponse(
            error="TEST_ERROR",
            message="Test message",
            details=[ErrorDetail(field="url", message="Invalid", code="url_error")]
        )
        dumped = error.model_dump()
        assert dumped["error"] == "TEST_ERROR"
        assert "timestamp" in dumped
        assert dumped["details"][0]["field"] == "url"