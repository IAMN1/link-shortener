"""``flask maintenance health`` against the answer ``/health`` gives.

The command called itself "Run all health checks" and looked at two
dependencies out of four. With Celery stopped it printed ``Database: OK``
and ``Redis: SKIPPED`` and exited 0, while ``/health`` in the same second
answered ``task_queue: unavailable`` and ``status: degraded`` -- so an
operator on the shell and a probe in the orchestrator read the same service
and disagreed about whether it was working.

``HealthSnapshot`` exists for exactly this. Its docstring: "Exists so that
every surface reporting health reports the *same* health. Callers that asked
each component separately drifted apart from each other". The command was
one of the callers that asked separately.
"""

import pytest
from flask.testing import FlaskCliRunner

from link_shortener.application.ports.health_check import HealthSnapshot
from link_shortener.infrastructure.configs.app.testing import TestingConfig


class HealthConfig(TestingConfig):
    """Testing profile with nothing to reach and nothing to seed."""

    LOGGING_ENABLED = False
    AUDIT_ENABLED = False
    AUTO_SEED_ROLES = False


@pytest.fixture
def app():
    """An application whose health checker the tests replace."""
    from link_shortener.web.app_factory import create_app

    return create_app(config=HealthConfig())


@pytest.fixture
def runner(app):
    return FlaskCliRunner(app)


def answering(app, snapshot):
    """
    Make the container's health checker answer with this snapshot.

    Args:
        app: The application under test.
        snapshot: What every surface should then report.
    """
    class Fixed:
        def snapshot(self):
            return snapshot

    app.container.health_check = Fixed()


EVERYTHING_UP = HealthSnapshot(
    database=True, cache=True, cache_configured=True,
    task_queue=True, rate_limiter=True,
)

QUEUE_DOWN = HealthSnapshot(
    database=True, cache=True, cache_configured=True,
    task_queue=False, rate_limiter=True,
)

LIMITER_DOWN = HealthSnapshot(
    database=True, cache=True, cache_configured=True,
    task_queue=True, rate_limiter=False,
)


class TestTheCommandReadsEveryDependencyTheProbeReads:

    def test_a_stopped_queue_is_a_failure_and_not_a_clean_exit(
        self, app, runner
    ):
        """
        The case that was silent: the command exited 0 with the worker
        gone, over a service ``/health`` was calling degraded.
        """
        answering(app, QUEUE_DOWN)

        result = runner.invoke(app.cli, ["maintenance", "health"])

        assert result.exit_code == 1, result.output
        assert "task queue" in result.output.lower()

    def test_a_limiter_that_stopped_enforcing_is_reported(self, app, runner):
        """
        The dependency that fails open: with its backend gone the limiter
        lets everything through, brute-force protection included, and no
        other surface says so.
        """
        answering(app, LIMITER_DOWN)

        result = runner.invoke(app.cli, ["maintenance", "health"])

        assert result.exit_code == 1, result.output
        assert "rate limiter" in result.output.lower()

    def test_a_healthy_service_is_reported_healthy(self, app, runner):
        answering(app, EVERYTHING_UP)

        result = runner.invoke(app.cli, ["maintenance", "health"])

        assert result.exit_code == 0, result.output
        for dependency in ("database", "cache", "task queue", "rate limiter"):
            assert dependency in result.output.lower()

    def test_a_dependency_that_never_answered_is_told_apart(self, app, runner):
        """
        ``timed_out`` is a distinct finding from "answered no", and the
        snapshot keeps them apart: "a probe that quietly reports the two
        alike hides which dependency is hanging".
        """
        answering(app, HealthSnapshot(
            database=True, cache=False, cache_configured=True,
            task_queue=True, rate_limiter=True, timed_out=("cache",),
        ))

        result = runner.invoke(app.cli, ["maintenance", "health"])

        assert result.exit_code == 1, result.output
        assert "timed out" in result.output.lower()

    def test_a_cache_nobody_configured_is_not_a_failure(self, app, runner):
        """
        The documented local setup runs with ``REDIS_ENABLED=false``, and
        reporting that as broken made a healthy install look broken -- the
        reason the old command skipped Redis at all.
        """
        answering(app, HealthSnapshot(
            database=True, cache=True, cache_configured=False,
            task_queue=True, rate_limiter=True,
        ))

        result = runner.invoke(app.cli, ["maintenance", "health"])

        assert result.exit_code == 0, result.output
        assert "not configured" in result.output.lower()
