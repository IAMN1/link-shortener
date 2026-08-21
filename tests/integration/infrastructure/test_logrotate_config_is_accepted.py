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
    # The entrypoint renders the template into the finished configuration,
    # so it is asked to do that first -- ``render`` does it and returns.
    # Rendering here instead would ask logrotate about a configuration this
    # test made rather than the one the container runs.
    #
    # One stream, because logrotate writes its whole debug account to
    # stderr -- both what it refused and what it would have done -- and
    # reading the two apart only decides which half a check is blind to.
    return subprocess.run(
        [
            "docker", "run", "--rm", IMAGE, "sh", "-c",
            f"mkdir -p /logs; {make_journals} "
            "/logrotate-entrypoint.sh render; "
            "logrotate -d --state /logs/state /etc/logrotate.d/link_shortener",
        ],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=300,
    )


@pytest.fixture(scope="module")
def renamed_journals():
    """The same question of a deployment that renamed its journals.

    The whole point of the template. Before it the names were written into
    the configuration literally, so a deployment setting ``LOG_FILENAME``
    kept its journals and lost its rotation -- silently, because
    ``missingok`` answers a missing file with nothing at all.

    Returns:
        The finished ``subprocess.CompletedProcess``.
    """
    names = ("service.log", "faults.log", "trail.log")
    make_journals = " ".join(
        f"head -c 200 /dev/urandom | base64 > /logs/{name};" for name in names
    )
    return subprocess.run(
        [
            "docker", "run", "--rm",
            "-e", "LOG_FILENAME=service",
            "-e", "ERROR_LOG_FILENAME=faults",
            "-e", "AUDIT_LOG_FILENAME=trail",
            IMAGE, "sh", "-c",
            f"mkdir -p /logs; {make_journals} "
            "/logrotate-entrypoint.sh render; "
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


class TestARenamedJournalIsStillRotated:
    """The fault the template exists for, asked of logrotate itself."""

    @pytest.mark.parametrize(
        "journal", ("service.log", "faults.log", "trail.log")
    )
    def test_the_configured_name_is_considered(self, journal, renamed_journals):
        assert f"considering log /logs/{journal}" in renamed_journals.stdout

    @pytest.mark.parametrize(
        "journal", ("application.log", "error.log", "audit.log")
    )
    def test_the_default_name_is_not(self, journal, renamed_journals):
        """Otherwise the template resolved to nothing and left the literals.

        A configuration naming both would pass the check above while
        rotating files nobody writes.
        """
        assert f"considering log /logs/{journal}" not in renamed_journals.stdout


class TestTheRotatorRefusesANameThatIsAPath:
    """The application checks these three settings and will not start on a
    bad one; the rotator is a separate container and would start anyway.

    ``/logs/../somewhere`` is a real path, ``create`` would make a file
    there and ``rotate`` would rename one -- for as long as it takes
    somebody to work out why the application is not coming up.
    """

    @pytest.mark.parametrize(
        "name", ("../escape", "logs/application", "..", ".hidden")
    )
    def test_it_refuses_and_says_so(self, name):
        result = subprocess.run(
            [
                "docker", "run", "--rm",
                "-e", f"LOG_FILENAME={name}",
                IMAGE, "/logrotate-entrypoint.sh", "render",
            ],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=300,
        )

        assert result.returncode != 0, result.stdout
        assert "is not a journal name" in result.stdout, result.stdout

    def test_an_ordinary_name_is_still_accepted(self):
        """The guard has to let the ordinary case through."""
        result = subprocess.run(
            [
                "docker", "run", "--rm",
                "-e", "LOG_FILENAME=service-2.v1",
                IMAGE, "/logrotate-entrypoint.sh", "render",
            ],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=300,
        )

        assert result.returncode == 0, result.stdout


class TestTheIntervalIsAWholeNumberOfSeconds:
    """``sleep`` is what makes the loop a schedule.

    Handed something it cannot read, it fails and returns at once, so the
    loop stops pausing: logrotate is called as fast as the container can
    call it and ``docker logs`` fills at the speed of the disk. One
    mistyped variable, and the symptom looks nothing like its cause.
    """

    @pytest.mark.parametrize("interval", ("abc", "60s", "", "0", "-1"))
    def test_a_value_sleep_cannot_use_is_refused(self, interval):
        # Under ``timeout`` inside the container, not merely under one on
        # ``subprocess``. The failure this guards against is a loop that
        # never pauses, and a Python-side timeout leaves that loop running:
        # measured while proving this test can fail, four containers were
        # left spinning and the next tests in the file timed out against a
        # busy daemon. The container has to be the thing that gives up.
        result = subprocess.run(
            [
                "docker", "run", "--rm",
                "-e", f"LOG_ROTATE_INTERVAL={interval}",
                IMAGE, "sh", "-c", "timeout 10 /logrotate-entrypoint.sh",
            ],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=60,
        )

        # The sentence rather than the status: a loop killed by ``timeout``
        # also exits non-zero, so the code alone would pass on the very
        # thing being guarded against.
        assert "not a positive whole number" in result.stdout, result.stdout
