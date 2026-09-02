"""Starting and reaching the test stack of real PostgreSQL and Redis.

Two directories need this: ``tests/integration/docker``, which checks what
only a real backend can show -- concurrency, advisory locks, the column
widths PostgreSQL enforces and SQLite ignores, and a real Redis behind the
limiter -- and ``tests/e2e``, which walks a user's whole path over the
same stack. Written once here so that both start the same containers, wait
the same way, and report a failure to start in the same words.

The distinction this module exists to keep: a missing Docker daemon is the
one condition worth skipping for, because the machine genuinely cannot run
these tests. Everything after that -- a port collision, a container that
never became healthy -- is a failure. Reporting the second as a skip once
turned a broken stack into a green run: ``492 passed, 16 skipped`` where
the suite had been printing ``508 passed``, with nothing but the arithmetic
to notice.
"""

import os
import subprocess
import time

import pytest
import redis
from sqlalchemy import create_engine, text

POSTGRES_URL = (
    "postgresql+psycopg://test_user:test_password@localhost:5433/test_shortener"
)
"""The database ``docker-compose.test.yml`` publishes on the loopback."""

REDIS_URL = "redis://:test_redis_pass@localhost:6380/0"
"""The cache the same file publishes."""

COMPOSE_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "dockers", "docker-compose.test.yml"
)
"""The stack definition, resolved from this file rather than the cwd."""


def run_compose(*args):
    """Run a ``docker compose`` subcommand against the test stack.

    Args:
        *args: Arguments following ``docker compose -f <file>``.

    Returns:
        The completed process.
    """
    cmd = ["docker", "compose", "-f", COMPOSE_FILE] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60)


def docker_is_available() -> bool:
    """Tell whether a Docker daemon can be reached at all.

    Returns:
        ``True`` when a daemon answers.
    """
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, text=True, timeout=20
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def diagnostics() -> str:
    """Collect what the stack has to say about why it did not come up.

    Returns:
        Container states and recent log lines, or a note on why not.
    """
    parts = []
    for label, args in (
        ("state", ("ps", "-a")),
        ("logs", ("logs", "--no-color", "--tail", "40")),
    ):
        try:
            result = run_compose(*args)
            parts.append(f"--- {label} ---\n{result.stdout or result.stderr}")
        except subprocess.SubprocessError as error:
            parts.append(f"--- {label} unavailable: {error} ---")
    return "\n".join(parts)


def _wait_for(check, max_retries=30, delay=1) -> bool:
    """Poll a check until it answers or the retries run out."""
    for _ in range(max_retries):
        try:
            if check():
                return True
        except Exception:
            pass
        time.sleep(delay)
    return False


def postgres_answers() -> bool:
    """Ask PostgreSQL for one row."""
    engine = create_engine(POSTGRES_URL)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    engine.dispose()
    return True


def redis_answers() -> bool:
    """Ping Redis."""
    client = redis.from_url(REDIS_URL)
    client.ping()
    client.close()
    return True


def start() -> None:
    """Bring the stack up and wait until both services answer.

    Skips the calling test only when no Docker daemon is reachable; a
    daemon that is up but a stack that will not start is a failure.

    Raises:
        Failed: Through ``pytest.fail``, when the stack does not come up.
    """
    if not docker_is_available():
        pytest.skip(
            "Docker daemon is not reachable -- these tests require real "
            "PostgreSQL and Redis"
        )

    try:
        result = run_compose("up", "-d")
    except subprocess.SubprocessError as error:
        pytest.fail(f"Docker is running but `compose up` did not finish: {error}")

    if result.returncode != 0:
        pytest.fail(
            "Docker is running but the test stack failed to start.\n"
            f"{result.stderr or result.stdout}\n{diagnostics()}"
        )

    for check, name in ((postgres_answers, "PostgreSQL"), (redis_answers, "Redis")):
        if _wait_for(check):
            continue
        report = diagnostics()
        run_compose("down", "-v")
        pytest.fail(
            f"{name} did not become reachable within the timeout, although "
            f"Docker is running.\n{report}"
        )


def stop() -> None:
    """Take the stack down, volumes included."""
    run_compose("down", "-v")
