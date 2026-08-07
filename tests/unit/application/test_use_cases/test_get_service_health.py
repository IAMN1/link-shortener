from unittest.mock import Mock

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.health_check import HealthSnapshot
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


def _snapshot(database=True, cache=True, task_queue=True):
    """
    Build a health snapshot with the given component states.

    Args:
        database: Whether the database answered.
        cache: Whether the cache answered.
        task_queue: Whether the queue can accept work.

    Returns:
        A ``HealthSnapshot``.
    """
    return HealthSnapshot(
        database=database,
        cache=cache,
        cache_configured=True,
        task_queue=task_queue,
    )


class TestGetServiceHealthUseCase:
    """Tests for the GetServiceHealthUseCase."""

    def test_all_healthy(self, use_case, mock_health_check, context):
        mock_health_check.snapshot.return_value = _snapshot()

        result = use_case.execute(context)

        assert result.database is True
        assert result.redis is True
        assert result.task_queue is True

    def test_database_down(self, use_case, mock_health_check, context):
        mock_health_check.snapshot.return_value = _snapshot(database=False)

        result = use_case.execute(context)

        assert result.database is False
        assert result.redis is True
        assert result.task_queue is True

    def test_cache_down(self, use_case, mock_health_check, context):
        mock_health_check.snapshot.return_value = _snapshot(cache=False)

        result = use_case.execute(context)

        assert result.database is True
        assert result.redis is False
        assert result.task_queue is True

    def test_all_down(self, use_case, mock_health_check, context):
        mock_health_check.snapshot.return_value = _snapshot(
            database=False, cache=False, task_queue=False
        )

        result = use_case.execute(context)

        assert result.database is False
        assert result.redis is False
        assert result.task_queue is False


class TestAdminHealthMatchesTheProbe:
    """
    The admin panel and the container probe must not disagree.

    The use case used to run its own checks and keep the answer for 15
    seconds, so the two surfaces could report different states of the same
    component with nothing to say which was stale.
    """

    def test_the_state_is_read_from_the_shared_snapshot(
        self, use_case, mock_health_check, context
    ):
        mock_health_check.snapshot.return_value = _snapshot(cache=False)

        use_case.execute(context)

        mock_health_check.snapshot.assert_called_once()

    def test_a_second_call_observes_the_state_again(
        self, use_case, mock_health_check, context
    ):
        mock_health_check.snapshot.return_value = _snapshot(database=False)
        assert use_case.execute(context).database is False

        # The dependency recovers. A cached answer would keep reporting the
        # outage while /health already reported otherwise.
        mock_health_check.snapshot.return_value = _snapshot(database=True)
        assert use_case.execute(context).database is True
