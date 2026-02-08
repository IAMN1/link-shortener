from unittest.mock import Mock
import pytest

from src.link_shortener.domain.services.base_service import BaseService


@pytest.mark.unit
class TestBaseService:
    """Тесты для BaseService"""

    @pytest.fixture
    def base_service_with_logger(self, mock_logger):
        return BaseService(logger=mock_logger)
    
    @pytest.fixture
    def base_service_without_logger(self):
        return BaseService(logger=None)
    
    def test_log_debug_with_logger(self, base_service_with_logger, mock_logger):
        """Тест debug логирования"""
        # Act
        base_service_with_logger._log_debug('test_message', some_data='data')

        # Assert
        mock_logger.debug.assert_called_once_with('test_message', some_data='data')
    
    def test_log_debug_without_logger(self, base_service_without_logger):
        """Тест debug без логгера (не должен падать)"""
        # Act & Assert (нет исключений)
        base_service_without_logger._log_debug('test_message')
    
    def test_log_info_with_logger(self, base_service_with_logger, mock_logger):
        """Тест логирования info с логгером"""
        # Act
        base_service_with_logger._log_info("Test info", count=5)
        
        # Assert
        mock_logger.info.assert_called_once_with("Test info", count=5)
    
    def test_log_warning_with_logger(self, base_service_with_logger, mock_logger):
        """Тест логирования warning с логгером"""
        # Act
        base_service_with_logger._log_warning("Test warning", reason="test")
        
        # Assert
        mock_logger.warning.assert_called_once_with("Test warning", reason="test")
    
    def test_log_error_with_logger(self, base_service_with_logger, mock_logger):
        """Тест логирования error с логгером"""
        # Act
        base_service_with_logger._log_error("Test error", exc_info="details")
        
        # Assert
        mock_logger.error.assert_called_once_with("Test error", exc_info="details")

    def test_all_log_methods_without_logger(self, base_service_without_logger):
        """Тест всех методов логирования без логгера"""

        # Act & Assert без исключений 
        base_service_without_logger._log_debug('debug')
        base_service_without_logger._log_info('info')
        base_service_without_logger._log_warning('warning')
        base_service_without_logger._log_error('error')

    def test_service_initialization(self, ):
        """Тест инициализации сервиса"""
        mock_logger = Mock()

        # Act
        service = BaseService(logger=mock_logger)

        # Assert
        assert service._logger == mock_logger
        