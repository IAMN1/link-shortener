"""The shipped rotation configuration, read by the program that runs it.

``dockers/logrotate.conf`` is not code and nothing imports it, so the two
ways it can be wrong are both silent. The first -- naming a journal the
application does not write -- is checked without Docker, in
``tests/unit/infrastructure/test_logging/test_rotation_is_followed.py``.
The second is syntax, and only logrotate can answer it: a block it refuses
is skipped with a message on stderr, and the journals in it go on growing
while the rotator reports for duty every hour.

That is not hypothetical. Written the obvious way, this configuration said
``create 0640 1000 1000`` -- the uid the application runs under -- and the
Debian build answered ``unknown user '1000'`` and skipped both blocks. It
looked right, and it rotated nothing.

Docker is what has logrotate here; the machine this is developed on does
not, and installing it there is not something a test may do. Without
Docker the check skips, the way the rest of the suite's container-backed
checks do.
"""

import subprocess

import pytest

from tests.support.real_stack import docker_is_available


IMAGE = "link-shortener-logrotate:test"
"""Tagged apart from the image compose builds, so a suite run cannot leave
the stack pointing at something a test made."""

ROOT = __import__("pathlib").Path(__file__).resolve().parents[3]

JOURNALS = ("application.log", "error.log", "audit.log")


pytestmark = pytest.mark.skipif(
    not docker_is_available(), reason="no Docker to read the configuration with"
)


@pytest.fixture(scope="module")
def dry_run():
    """
    Build the rotator image and ask logrotate what it would do.

    The journals are made inside the container rather than mounted from
    the host: this asks about the configuration, and a bind mount would
    add the host's own permissions to the question.

    Returns:
        The finished ``subprocess.CompletedProcess``.
    """
    build = subprocess.run(
        [
            "docker", "build",
            "-f", "dockers/Dockerfile.logrotate",
            "-t", IMAGE,
            ".",
        ],
        cwd=ROOT, capture_output=True, text=True, timeout=600,
    )
    assert build.returncode == 0, build.stderr[-2000:]

    make_journals = " ".join(
        f"head -c 200 /dev/urandom | base64 > /logs/{name};" for name in JOURNALS
    )
    # One stream, because logrotate writes its whole debug account to
    # stderr -- both what it refused and what it would have done -- and
    # reading the two apart only decides which half a check is blind to.
    return subprocess.run(
        [
            "docker", "run", "--rm", IMAGE, "sh", "-c",
            f"mkdir -p /logs; {make_journals} "
            "logrotate -d --state /logs/state /etc/logrotate.d/link_shortener",
        ],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=300,
    )


class TestLogrotateAcceptsWhatWeShip:

    def test_it_reports_no_error(self, dry_run):
        assert "error:" not in dry_run.stdout, dry_run.stdout[-2000:]

    def test_it_ends_well(self, dry_run):
        assert dry_run.returncode == 0, dry_run.stdout[-2000:]

    def test_it_took_both_blocks(self, dry_run):
        """
        Two, not three: ``application.log`` and ``error.log`` share a
        block, and the audit journal has one of its own because it is kept
        for a year rather than a fortnight.
        """
        assert "Handling 2 logs" in dry_run.stdout, dry_run.stdout[-2000:]

    @pytest.mark.parametrize("journal", JOURNALS)
    def test_every_journal_is_considered(self, journal, dry_run):
        """
        Parsing is not covering: a block logrotate accepts can still name
        a path that matches nothing. ``-d`` prints one "considering log"
        per file it found, which is the only place the two meet.
        """
        assert f"considering log /logs/{journal}" in dry_run.stdout
