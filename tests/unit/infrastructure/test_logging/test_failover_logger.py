
from unittest.mock import Mock

from link_shortener.application.ports.logger.logger import Logger
from link_shortener.infrastructure.logging.failover_logger import FailoverLogger


class TestFailoverLogger:

    def test_initital_use_primary(self):

        # Arrange
        primary = Mock(spec=Logger)
        secondary = Mock(spec=Logger)
        logger = FailoverLogger(
            [
                (primary, "primary"), 
                (secondary, "secondary")
            ],
            check_interval=0.1
        )

        # Act
        logger.info("test")

        # Assert
        primary.info.assert_called_once_with("test")
        secondary.info.assert_not_called()
        logger._stop_event.set()
    
    def test_failover_on_error(self):

        # Arrange
        primary = Mock(spec=Logger)
        primary.info.side_effect = Exception("fail")
        secondary = Mock(spec=Logger)
        logger = FailoverLogger(
            [
                (primary, "primary"), 
                (secondary, "secondary")
            ], 
            check_interval=0.1
        )

        # Act
        logger.info("test")
        
        # Assert
        primary.info.assert_called_once()
        secondary.info.assert_called_once_with("test")
        logger._stop_event.set()
