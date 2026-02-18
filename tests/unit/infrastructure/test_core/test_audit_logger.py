from link_shortener.domain.value_objects.original_url import OriginalUrl
from link_shortener.domain.value_objects.short_code import ShortCode
from link_shortener.domain.value_objects.url_hash import UrlHash
from link_shortener.infrastructure.cache.redis_cache import Link
from link_shortener.infrastructure.core.audit_logger import StructlogAuditLogger


# ------------------------------------------------------------------
# TestConfigFactory
# ------------------------------------------------------------------
class TestStructlogAuditLogger:
    """Tests for StructlogAuditLogger."""

    def test_log_without_optional_args(self, mock_structlog, sample_link):
        """Should log url_created event without optional user_ip."""

        # Arrange
        logger = StructlogAuditLogger()
        
        # Act
        logger.log_url_created(sample_link)  # без user_ip
        
        # Assert
        mock_structlog.info.assert_called_once()
        _, kwargs = mock_structlog.info.call_args
        assert kwargs.get('user_ip') is None

    def test_mask_url(self, mock_structlog):
        """Should mask long URLs in logs."""

        # Arrange
        logger = StructlogAuditLogger()
        long_url = 'https://test.com/' + 'a' * 500
        link = Link.create(
            url_hash=UrlHash('a'*64),
            short_code=ShortCode('abc123'),
            original_url=OriginalUrl(long_url)
        )

        # Act
        logger.log_url_created(link)
        
        # Assert
        mock_structlog.info.assert_called_once()
        args, kwargs = mock_structlog.info.call_args
        # ожидаем, что original_url был обрезан
        masked = kwargs['original_url']
        assert len(masked) < len(long_url)
        assert masked.startswith('https://')
        assert '...' in masked

    def test_log_url_created(self, mock_structlog, sample_link):
        """Should log url_created event with correct fields."""

        logger = StructlogAuditLogger()

        # Act
        logger.log_url_created(sample_link, user_ip="127.0.0.1")

        # Assert
        mock_structlog.info.assert_called_once()
        args, kwargs = mock_structlog.info.call_args
        assert args[0] == "url_created"
        assert kwargs["short_code"] == sample_link.short_code.value
        assert kwargs["user_ip"] == "127.0.0.1"

    def test_log_url_accessed(self, mock_structlog, sample_link):
        """Should log url_accessed event with correct fields."""

        logger = StructlogAuditLogger()
        
        # Act
        logger.log_url_accessed(sample_link, user_ip="127.0.0.1", user_agent="Mozilla")
        
        # Assert
        mock_structlog.info.assert_called_once()
        args, kwargs = mock_structlog.info.call_args
        assert args[0] == 'url_accessed'
        assert kwargs['clicks'] == sample_link.clicks