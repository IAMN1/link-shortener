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


def _snapshot(
    database=True, cache=True, task_queue=True, rate_limiter=True,
    cache_configured=True, timed_out=(),
):
    """
    Build a health snapshot with the given component states.

    Args:
        database: Whether the database answered.
        cache: Whether the cache answered.
        task_queue: Whether the queue can accept work.
        rate_limiter: Whether request limits are being enforced.
        cache_configured: Whether a cache backend exists at all.
        timed_out: Components that ran out of the check's budget.

    Returns:
        A ``HealthSnapshot``.
    """
    return HealthSnapshot(
        database=database,
        cache=cache,
        cache_configured=cache_configured,
        task_queue=task_queue,
        rate_limiter=rate_limiter,
        timed_out=timed_out,
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


class TestTheLoggingStateIsReadWhenThereIsAReaderForIt:
    """The section can be dropped on the way out and nothing noticed.

    Replacing ``self.logging_status.read() if self.logging_status else
    None`` with a bare ``None`` passes everything else -- and takes with it
    the whole point of ``LoggingStatus``, which exists so that an audit
    trail that stopped being written stops looking like one that is fine.
    Every test here built the use case without a reader, so the branch that
    reads one was never taken.
    """

    def test_the_reader_is_asked_and_its_answer_is_carried_out(
        self, mock_health_check, mock_logger, context
    ):
        from link_shortener.application.ports.logging_status import (
            LoggingStatus,
        )

        state = LoggingStatus(
            worker=4242,
            logger_active="structlog",
            logger_dropped_calls=11,
            logger_failed_checks=12,
            logger_lost_log_lines=13,
            audit_active="standard_audit",
            audit_dropped_calls=21,
            audit_failed_checks=22,
            audit_lost_log_lines=23,
        )
        reader = Mock()
        reader.read.return_value = state
        mock_health_check.snapshot.return_value = _snapshot()
        use_case = GetServiceHealthUseCase(
            health_check_port=mock_health_check,
            logger=mock_logger,
            logging_status=reader,
        )

        result = use_case.execute(context)

        reader.read.assert_called_once_with()
        assert result.logging is state

    def test_without_a_reader_the_section_is_absent_rather_than_empty(
        self, use_case, mock_health_check, context
    ):
        """Zero would read as "nothing was lost" rather than "nobody
        looked", which is the distinction the field exists to keep."""
        mock_health_check.snapshot.return_value = _snapshot()

        assert use_case.execute(context).logging is None


class TestEachFieldComesFromItsOwnFieldOfTheSnapshot:
    """One component down at a time, because all-True tells none apart.

    ``rate_limiter=state.database`` in place of ``state.rate_limiter``
    passes everything else. What it costs is the one component nothing else
    reports -- a limiter that has lost its
    backend lets everything through, brute-force protection on the auth
    endpoints included, and the admin panel goes on saying it is enforcing.
    ``rate_limiter`` was not asserted by any test here, and ``_snapshot``
    did not even set it.
    """

    FIELDS = [
        ("database", "database"),
        ("cache", "redis"),
        ("task_queue", "task_queue"),
        ("rate_limiter", "rate_limiter"),
    ]

    @pytest.mark.parametrize("taken_down, reported_as", FIELDS)
    def test_the_one_that_is_down_is_the_one_reported_down(
        self, use_case, mock_health_check, context, taken_down, reported_as
    ):
        """
        Args:
            taken_down: Field of the snapshot that is down.
            reported_as: Attribute of the answer that must report it.
        """
        mock_health_check.snapshot.return_value = _snapshot(
            **{taken_down: False}
        )

        result = use_case.execute(context)

        assert getattr(result, reported_as) is False
        assert [
            other for _, other in self.FIELDS
            if other != reported_as and getattr(result, other) is not True
        ] == []


class TestWhatTheBooleansCannotSayIsCarriedBeside:
    """Two fields of the snapshot stopped here, and both are distinctions.

    ``cache`` is ``True`` on a deployment with no cache at all -- a cache
    with nothing to connect to cannot be down -- so the admin surfaces
    drew "Redis: answering" over a service running ``REDIS_ENABLED=false``.
    ``timed_out`` names the dependency that is hanging, which "answered
    no" cannot. ``/health`` and ``flask maintenance health`` read both
    off this same snapshot; only the answer an operator watches dropped
    them.
    """

    def test_a_cache_nobody_configured_is_told_from_a_working_one(
        self, use_case, mock_health_check, context
    ):
        mock_health_check.snapshot.return_value = _snapshot(
            cache=True, cache_configured=False
        )

        result = use_case.execute(context)

        # Both, and they say different things: the cache answered, and
        # there is no cache to answer.
        assert result.redis is True
        assert result.cache_configured is False

    def test_a_configured_cache_says_so(
        self, use_case, mock_health_check, context
    ):
        # The premise: without it the assertion above is satisfied by a
        # field that is False whatever the snapshot holds.
        mock_health_check.snapshot.return_value = _snapshot()

        assert use_case.execute(context).cache_configured is True

    def test_what_ran_out_of_budget_is_named(
        self, use_case, mock_health_check, context
    ):
        mock_health_check.snapshot.return_value = _snapshot(
            task_queue=False, timed_out=("task_queue",)
        )

        result = use_case.execute(context)

        assert result.task_queue is False
        assert result.timed_out == ("task_queue",)

    def test_nothing_hanging_names_nothing(
        self, use_case, mock_health_check, context
    ):
        mock_health_check.snapshot.return_value = _snapshot(task_queue=False)

        assert use_case.execute(context).timed_out == ()


class TestAdminHealthMatchesTheProbe:
    """
    The admin panel and the container probe must not disagree.

    Both read one snapshot. Running its own checks here and keeping the
    answer for 15 seconds lets the two surfaces report different states of
    the same component, with nothing to say which is stale.
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
