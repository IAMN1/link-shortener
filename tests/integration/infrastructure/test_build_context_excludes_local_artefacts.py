"""What the build context hands Docker, asked of Docker.

``.dockerignore`` is not code and nothing imports it, so the way it goes
wrong is silent. ``COPY ./src ./src/`` takes the directory as it stands on
the machine doing the build, and a working tree the package has been
installed into carries ``src/link_shortener.egg-info`` -- untracked by git,
and no reason for Docker to skip it.

It reached the image and then answered for the package: ``/app/src``
precedes site-packages on ``sys.path``, so
``importlib.metadata.version("link-shortener")`` in the container said
0.1.0 -- the version that egg-info happened to be written at -- while
``link_shortener-0.9.0.dist-info`` sat beside it saying otherwise. Nothing
in the application asks that question today, which is exactly why the
image could carry a false answer for as long as it did.

Only Docker can say whether a pattern excludes a path. Its matching is its
own, and ``*`` does not cross a ``/``: ``*.egg-info`` would have left
``src/link_shortener.egg-info`` in, and a test that read the patterns
itself would have agreed with whichever reading it implemented. So this
builds a context-only image from the real root and looks at what arrived.

Docker is what applies the file; the check skips without it, the way the
rest of the suite's container-backed checks do.
"""

import pathlib
import subprocess

import pytest

from tests.support.real_stack import docker_is_available


ROOT = pathlib.Path(__file__).resolve().parents[3]

IMAGE = "link-shortener-context:test"
"""Tagged apart from the image compose builds, so a suite run cannot leave
the stack pointing at something a test made."""

BASE = "python:3.12-slim-bookworm"
"""The base the real Dockerfile uses, so this pulls nothing new."""

CONTEXT_ONLY = f"""
FROM {BASE}
COPY ./src /probe/src
COPY ./migrations /probe/migrations
"""
"""Only the copies whose sources are directories.

A directory is what carries something nobody chose to send; the single
files the Dockerfile copies -- `alembic.ini`, `requirements.txt` -- are
named one by one and cannot.
"""

pytestmark = pytest.mark.skipif(
    not docker_is_available(), reason="no Docker to apply .dockerignore with"
)


@pytest.fixture(scope="module")
def arrived():
    """Build the context-only image and list what should not be in it."""

    build = subprocess.run(
        ["docker", "build", "-f", "-", "-t", IMAGE, str(ROOT)],
        input=CONTEXT_ONLY,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert build.returncode == 0, f"context build failed:\n{build.stderr[-2000:]}"

    listing = subprocess.run(
        [
            "docker", "run", "--rm", IMAGE,
            "find", "/probe", "-name", "*.egg-info", "-o", "-name", "__pycache__",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert listing.returncode == 0, listing.stderr

    yield [line for line in listing.stdout.splitlines() if line.strip()]

    subprocess.run(["docker", "image", "rm", "-f", IMAGE], capture_output=True)


class TestNothingLocalRidesAlong:
    """The artefacts a working tree grows, kept out of the image."""

    def test_no_egg_info_reaches_the_image(self, arrived):
        """It would answer for the package, and answer with a stale version."""

        found = [path for path in arrived if path.endswith(".egg-info")]

        assert not found, (
            f"{found} reached the image: `.dockerignore` has to exclude it as "
            "`**/*.egg-info`, since `*` does not cross a `/`"
        )

    def test_no_bytecode_cache_reaches_the_image(self, arrived):
        """Compiled for another interpreter, and stale the moment it is copied."""

        found = [path for path in arrived if path.endswith("__pycache__")]

        assert not found, f"{found} reached the image"
