"""Four writers and a rotation, which is the deployment this runs in.

``dockers/docker-compose.yml`` starts gunicorn with ``--workers 4``, and
each worker builds the application for itself: four processes hold four
descriptors on the same ``application.log``. Rotation is therefore not a
question about a handler but a question about four of them at once, and
the single-process checks in
``tests/unit/infrastructure/test_logging/test_rotation_is_followed.py``
cannot ask it -- a handler that rotates for itself passes every one of
them.

This is the measurement that decided the design, kept as a test. Over
80 000 records through four processes, ``RotatingFileHandler`` lost between
10 and 16 per cent of them -- it truncates the base file while the other
three are writing into it -- and raised between 5 and 14 write errors,
which in this application do not go to stderr but reach the caller and are
counted by ``FailoverService``. The same load through
``WatchedFileHandler`` with the rotation outside lost nothing, three runs
out of three. The numbers are written up in ``docs/decisions.md``; what is
here is the smaller, faster version of the same load, run every time.

It is a "spawn" test on purpose: the writers are separate processes because
separate processes are the thing being tested, and no amount of threads
would reproduce four descriptors and four flushes.
"""

import multiprocessing
import re

import pytest

from tests.support.rotation_writers import rotate_on_signal, write_records


WRITERS = 4
"""What ``GUNICORN_WORKERS`` is set to in ``.env.example``."""

RECORDS_EACH = 1500
"""4 x 1500 records of ~265 bytes: about 1.5 MB of journal."""

BEFORE_THE_ROTATION = 200
"""Records each writer puts down before the renames begin, so that the
rotation is performed on a journal being written rather than on an empty
one."""

ROTATIONS = 3

RECORD = re.compile(r"^R (\d+) (\d+) ", re.MULTILINE)


@pytest.fixture(scope="module")
def written_under_rotation(tmp_path_factory):
    """
    Run the four writers while a fifth process rotates underneath them.

    Once for the three checks below rather than once each: they are three
    questions about one run, and the load is the expensive part.

    Returns:
        Tuple of the writers' exit codes, how many rotations happened, and
        the directory everything was written into.
    """
    context = multiprocessing.get_context("spawn")
    tmp_path = tmp_path_factory.mktemp("rotation")
    path = tmp_path / "application.log"
    path.touch()

    # The writers and the rotator, and nobody else: the barrier releases
    # when all five are at it, which is the moment every writer has
    # records down and more to write.
    barrier = context.Barrier(WRITERS + 1)
    generations = context.Value("i", 0)

    rotator = context.Process(
        target=rotate_on_signal, args=(str(path), barrier, ROTATIONS, generations)
    )
    rotator.start()

    writers = [
        context.Process(
            target=write_records,
            args=(str(path), RECORDS_EACH, index, barrier, BEFORE_THE_ROTATION),
        )
        for index in range(WRITERS)
    ]
    for writer in writers:
        writer.start()
    for writer in writers:
        writer.join(timeout=120)

    rotator.join(timeout=30)

    return [writer.exitcode for writer in writers], generations.value, tmp_path


def records_on_disk(directory):
    """
    Every record found across the journal and its rotated generations.

    Args:
        directory: Where the writers and the rotator left their files.

    Returns:
        List of (writer, number) pairs, one per record, duplicates kept --
        a record written twice is as wrong as one lost, and counting a set
        would hide it.
    """
    return [
        found
        for file in sorted(directory.iterdir())
        for found in RECORD.findall(file.read_text(encoding="utf-8", errors="replace"))
    ]


class TestNothingIsLostWhenTheFileIsRotatedUnderneath:

    def test_the_rotation_actually_happened(self, written_under_rotation):
        """
        Otherwise everything below passes over a load nobody rotated.

        A rotation that never fired is the way this test would go quietly
        green if the writers got slower or the size went up.
        """
        _exits, rotations, _directory = written_under_rotation

        assert rotations == ROTATIONS, f"the journal was rotated {rotations} times"

    def test_the_journal_at_the_live_name_goes_on_receiving_records(
        self, written_under_rotation
    ):
        """
        Losing nothing is not enough: a writer that never reopens loses
        nothing either.

        It keeps its descriptor on the file that was moved aside, so every
        record after the first rotation is written into an archive -- and
        the journal an operator reads, and a retention policy keeps
        newest, stays empty until the process restarts. Counting records
        across all the files cannot tell the two apart, and this is what
        does: after the last rotation the writers are still running, so all
        four have to appear at the live name.
        """
        _exits, _rotations, directory = written_under_rotation

        live = (directory / "application.log").read_text(encoding="utf-8")
        writers_seen = {writer for writer, _number in RECORD.findall(live)}

        assert writers_seen == {str(index) for index in range(WRITERS)}

    def test_every_record_written_is_on_disk_exactly_once(
        self, written_under_rotation
    ):
        _exits, _rotations, directory = written_under_rotation

        found = records_on_disk(directory)
        expected = {
            (str(index), str(number))
            for index in range(WRITERS)
            for number in range(RECORDS_EACH)
        }

        assert len(found) == len(expected), (
            f"{len(expected)} records were written and {len(found)} are on disk"
        )
        assert set(found) == expected

    def test_no_writer_had_a_write_fail(self, written_under_rotation):
        """
        The other half of the loss, and the one an operator sees first.

        These handlers re-raise a failed write for this application's own
        records, so a failure here leaves the process with a non-zero exit
        code. In the running application it reaches ``FailoverService``
        instead, which moves the work and counts it in ``dropped_calls``.
        """
        exits, _rotations, _directory = written_under_rotation

        assert exits == [0] * WRITERS
