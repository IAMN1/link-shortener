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

import re

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

SCHEMA_MISSING = HealthSnapshot(
    database=True, cache=True, cache_configured=True,
    task_queue=True, rate_limiter=True, database_schema=False,
)
"""Everything answers, and the database holds none of our tables."""


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


class TestTheRefusalReachesTheErrorStream:
    """A cron line that keeps only stderr still learns what was wrong.

    The report itself stays whole on stdout, because splitting a table
    across two streams leaves whoever reads one of them a report with
    holes in it. What was missing was the verdict: the command exited 1
    and wrote nothing to stderr at all, so a schedule that redirects
    output away -- which is what a schedule usually does -- had an exit
    code and no sentence anywhere.
    """

    def test_the_failing_dependency_is_named_on_stderr(self, app, runner):
        answering(app, LIMITER_DOWN)

        result = runner.invoke(app.cli, ["maintenance", "health"])

        assert result.exit_code == 1
        assert "Unhealthy" in result.stderr, result.stderr
        assert "Rate limiter" in result.stderr, result.stderr

    def test_the_report_still_goes_to_stdout_whole(self, app, runner):
        """Four lines, none of them diverted to the other stream."""
        answering(app, LIMITER_DOWN)

        result = runner.invoke(app.cli, ["maintenance", "health"])

        for name in ("Database", "Cache", "Task queue", "Rate limiter"):
            assert re.search(rf"^{name}: ", result.stdout, re.M), result.stdout

    def test_a_database_without_the_schema_is_named_too(self, app, runner):
        """
        The one fault whose row is not spelled ``FAILED``.

        A live connection holding none of this application's tables is a
        failure the verdict counts, and its row says ``no schema -- run
        `flask alembic upgrade head` `` instead. The verdict list was
        built by matching the word ``FAILED``, so for this fault alone it
        came out empty: measured, stderr was exactly ``Unhealthy: ``,
        naming nothing -- to a schedule that keeps only the error stream,
        an exit code and a sentence with the subject missing, for the one
        failure whose remedy is a single documented command.
        """
        answering(app, SCHEMA_MISSING)

        result = runner.invoke(app.cli, ["maintenance", "health"])

        assert result.exit_code == 1
        assert "Database" in result.stderr, result.stderr

    def test_the_verdict_never_names_nothing(self, app, runner):
        """
        The property behind the case above, stated once: an exit of 1
        with an empty list is the shape of the defect, whichever row
        produces it.
        """
        for snapshot in (SCHEMA_MISSING, LIMITER_DOWN, QUEUE_DOWN):
            answering(app, snapshot)

            result = runner.invoke(app.cli, ["maintenance", "health"])

            assert result.exit_code == 1
            verdict = [
                line for line in result.stderr.splitlines()
                if line.startswith("Unhealthy:")
            ]
            assert verdict, result.stderr
            assert verdict[0].removeprefix("Unhealthy:").strip(), (
                f"the verdict named no dependency: {verdict[0]!r}"
            )

    def test_a_healthy_run_says_nothing_on_stderr(self, app, runner):
        """Silence is the whole point of the error stream."""
        answering(app, EVERYTHING_UP)

        result = runner.invoke(app.cli, ["maintenance", "health"])

        assert result.exit_code == 0
        assert result.stderr == "", result.stderr

    def test_a_dependency_that_hung_is_named_too(self, app, runner):
        """A hang reaches the verdict the same way a refusal does.

        ``timed_out`` is a distinct finding, but it is not a separate
        state: the implementation marks the dependency that did not
        answer as down as well, so it shows FAILED in the table and the
        verdict picks it up from there. A snapshot claiming a component
        both answered and timed out is not one the probe produces, and a
        test that built one would hold a rule nothing has.
        """
        answering(app, HealthSnapshot(
            database=True, cache=False, cache_configured=True,
            task_queue=True, rate_limiter=True, timed_out=("cache",),
        ))

        result = runner.invoke(app.cli, ["maintenance", "health"])

        assert result.exit_code == 1
        assert "Unhealthy: Cache" in result.stderr, result.stderr
        # The distinction survives on stdout, where the report is.
        assert "timed out" in result.stdout.lower()


class TestTheJournalsThisProcessCouldOpen:
    """The command an operator runs when the journal is the thing wrong.

    Measured with ``datas/logs/application.log`` replaced by a directory:
    before the bootstrap survived it, this command ended in an
    ``IsADirectoryError`` traceback and exit code 1, because building the
    application to run it opened the same file. It now runs, and says
    which of the three journals this process has.
    """

    def test_the_journals_that_opened_are_named(self, app, runner):
        answering(app, EVERYTHING_UP)

        result = runner.invoke(app.cli, ["maintenance", "health"])

        assert re.search(r"^Opened: ", result.stdout, re.M), result.stdout

    def test_a_journal_that_would_not_open_is_named_with_its_reason(
        self, app, runner, monkeypatch
    ):
        """
        Whole, and not clipped into the label column.

        Put through the column formatter as ``Journal application:`` it
        came out ``Journal appl… UNAVAILABLE``, which drops the one word
        the reader is here for -- which of the three files it is. The
        reason travels whole for the same reason: "the journal is
        broken" does not say whether to fix a directory, a mode or a
        disk.
        """
        from link_shortener.application.ports.logging_status import (
            JournalUnavailable,
        )
        from link_shortener.infrastructure.cli.adapters import flask as adapter

        answering(app, EVERYTHING_UP)
        monkeypatch.setattr(
            adapter, "journals_written", lambda: ("error", "audit")
        )
        monkeypatch.setattr(
            adapter,
            "journals_unavailable",
            lambda: (
                JournalUnavailable(
                    "application",
                    "[Errno 21] Is a directory: "
                    "'/app/datas/logs/application.log'",
                ),
            ),
        )

        result = runner.invoke(app.cli, ["maintenance", "health"])

        assert "application ([Errno 21] Is a directory:" in result.stdout, (
            result.stdout
        )
        # Not part of the verdict: the exit code is the state of the four
        # dependencies, `/health` answers with the same one, and a command
        # that failed where the endpoint passed would be the two surfaces
        # disagreeing that `HealthSnapshot` exists to prevent.
        assert result.exit_code == 0, result.output

    def test_a_deployment_that_writes_no_journals_says_so(
        self, app, runner, monkeypatch
    ):
        """``LOG_TO_FILE=false`` is a configuration, not a fault.

        Nothing failed to open and nothing is being written: reading the
        failures alone, the two states are one, which is the trap
        ``cache_configured`` was added to the row above for.
        """
        from link_shortener.infrastructure.cli.adapters import flask as adapter

        answering(app, EVERYTHING_UP)
        monkeypatch.setattr(adapter, "journals_written", tuple)

        result = runner.invoke(app.cli, ["maintenance", "health"])

        assert re.search(r"^Opened: +not configured", result.stdout, re.M), (
            result.stdout
        )
