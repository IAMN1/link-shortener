from unittest.mock import Mock

from link_shortener.application.context import RequestContext
from link_shortener.application.use_cases.stats.get_service_health import GetServiceHealthUseCase
import pytest


@pytest.fixture
def mock_health_check():
    return Mock()


@pytest.fixture
def mock_logger():
    logger = Mock()
    logger.bind.return_value = Mock()
    return logger


@pytest.fixture
def context():
    return RequestContext(
        request_id="req-1",
        remote_addr="127.0.0.1",
        user_agent="Mozilla/5.0",
        request_path="/api/v1/admin/health",
        request_method="GET",
    )


@pytest.fixture
def use_case(mock_health_check, mock_logger):
    return GetServiceHealthUseCase(
        health_check_port=mock_health_check,
        logger=mock_logger,
    )


class TestGetServiceHealthUseCase:
    """Tests for the GetServiceHealthUseCase."""

    def test_all_healthy(
        self, use_case, mock_health_check, context
    ):
        mock_health_check.check_database.return_value = True
        mock_health_check.check_cache.return_value = True
        mock_health_check.check_task_queue.return_value = True

        result = use_case.execute(context)

        assert result.database is True
        assert result.redis is True
        assert result.task_queue is True

    def test_database_down(
        self, use_case, mock_health_check, context
    ):
        mock_health_check.check_database.return_value = False
        mock_health_check.check_cache.return_value = True
        mock_health_check.check_task_queue.return_value = True

        result = use_case.execute(context)

        assert result.database is False
        assert result.redis is True
        assert result.task_queue is True

    def test_cache_down(
        self, use_case, mock_health_check, context
    ):
        mock_health_check.check_database.return_value = True
        mock_health_check.check_cache.return_value = False
        mock_health_check.check_task_queue.return_value = True

        result = use_case.execute(context)

        assert result.database is True
        assert result.redis is False
        assert result.task_queue is True

    def test_all_down(
        self, use_case, mock_health_check, context
    ):
        mock_health_check.check_database.return_value = False
        mock_health_check.check_cache.return_value = False
        mock_health_check.check_task_queue.return_value = False

        result = use_case.execute(context)

        assert result.database is False
        assert result.redis is False
        assert result.task_queue is False
