from link_shortener.infrastructure.logging.structlog_logger import StructLogger


# ------------------------------------------------------------------
# TestStructLogger
# ------------------------------------------------------------------
class TestStructLogger:
    """Tests for StructLogger."""

    def test_logger_delegates(self, mock_structlog):
        """Should delegate all log methods to structlog."""
        
        # Arrange
        logger = StructLogger("Test")

        # Acts
        logger.debug("debug message", extra="data")
        logger.info("info message")
        logger.warning("warning message")
        logger.error("error message")
        logger.exception("exception message", exc_info=ValueError("Testing"))

        # Asserts
        mock_structlog.debug.assert_called_once_with("debug message", extra="data")
        mock_structlog.info.assert_called_once_with("info message")
        mock_structlog.warning.assert_called_once_with("warning message")
        mock_structlog.error.assert_called_once_with("error message")
        mock_structlog.exception.assert_called_once()
        args, kwargs = mock_structlog.exception.call_args
        assert args[0] == "exception message"
        assert isinstance(kwargs['exc_info'], ValueError)
        assert str(kwargs['exc_info']) == "Testing"
