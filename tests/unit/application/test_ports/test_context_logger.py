from unittest.mock import Mock

from link_shortener.application.ports.logger.logger import ContextLogger


class TestContextLogger:
    
    def test_context_logger_to_all_calls(self):

        inner = Mock()
        logger = ContextLogger(inner, {"ctx": "value"})

        logger.debug("msg", extra="data")
        inner.debug.assert_called_once_with("msg", ctx="value", extra="data")

        logger.info("msg")
        inner.info.assert_called_once_with("msg", ctx="value")

        logger.warning("msg")
        inner.warning.assert_called_once_with("msg", ctx="value")

        logger.error("msg")
        inner.error.assert_called_once_with("msg", ctx="value")

        exc = ValueError()
        logger.exception("msg", exc_info=exc, extra="exc_data")
        inner.exception.assert_called_once()
        inner.exception.assert_called_once_with(
            "msg", exc, ctx="value", extra="exc_data"
        )