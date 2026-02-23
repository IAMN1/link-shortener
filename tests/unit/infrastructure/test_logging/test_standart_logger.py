from unittest.mock import Mock, patch

from link_shortener.infrastructure.logging.standart_logger import StandartLogger


class TestStandartLogger:

    def test_log_methods(self):
        """Tests for StandartLogger adapter."""

        with patch('logging.getLogger') as mock_get_logger:
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            logger = StandartLogger("test")

            logger.debug("debug msg", extra="data")
            mock_logger.debug.assert_called_once_with("debug msg - %s", {'extra': 'data'})

            logger.info("info msg")
            mock_logger.info.assert_called_once_with("info msg")

            logger.warning("warning msg")
            mock_logger.warning.assert_called_once_with("warning msg")

            logger.error("error msg")
            mock_logger.error.assert_called_once_with("error msg")

            exc = ValueError("test")
            logger.exception("exception msg", exc_info=exc)
            mock_logger.exception.assert_called_once_with("exception msg", exc_info=exc, extra={})

            mock_logger.setLevel.assert_called_once()
