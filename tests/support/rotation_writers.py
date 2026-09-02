"""The processes ``test_rotation_under_several_writers`` runs.

They live here rather than in the test module because the test starts them
with the ``spawn`` start method, which imports the module holding the
target by name in the child. ``fork`` would take the test module along with
everything pytest has loaded into it; ``spawn`` asks only for what these
two functions need, and behaves the same on Linux and macOS.

The two meet at a barrier rather than by watching the file grow. Sizes
looked like the honest way to do it -- rotate at 32 KB, the way logrotate
rotates at 100 MB -- and it made the test decide nothing: four writers put
1.5 MB down in about fifteen milliseconds, which is less than it takes to
start the process that was supposed to rotate underneath them, so all
three rotations happened after the last record was written. The barrier
puts the renames where the test says they are: in the middle of the load,
with every writer still holding records.
"""

import logging
import os
import time
from pathlib import Path

from link_shortener.infrastructure.logging.handlers.raising import (
    RaisingWatchedFileHandler,
)


WRITER_LOGGER = "link_shortener.test.rotation.writer"
"""A name this application owns, so a failed write raises rather than
printing to stderr -- which is what makes a non-zero exit code mean "a
write failed"."""

PADDING = "x" * 240
"""Brings a record to about the 265 bytes the application's own JSON
records were measured at."""

BREATH = 0.001
"""Seconds a writer waits every hundred records after the barrier.

Not there to be gentle: it is what keeps the second half of the load
longer than the burst of renames on any machine, fast or slow, since both
sides are then counted in sleeps rather than in instructions.
"""


def write_records(path: str, count: int, index: int, barrier, before_barrier: int) -> None:
    """
    Write numbered records the way a gunicorn worker does: one handler,
    one long-lived descriptor, no rotation of its own.

    Args:
        path: The journal every writer shares.
        count: How many records this writer produces in total.
        index: Which writer this is, so records can be told apart.
        barrier: Met once the first records are down, and released when
            the rotator is about to start renaming.
        before_barrier: How many records to write before meeting it.
    """
    log = logging.getLogger(f"{WRITER_LOGGER}.{index}")
    log.setLevel(logging.INFO)
    log.propagate = False
    handler = RaisingWatchedFileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(handler)

    for number in range(count):
        if number == before_barrier:
            barrier.wait()
        # A failed write raises out of here and takes the process with it,
        # which is what the test reads off the exit code.
        log.info("R %d %d %s", index, number, PADDING)
        if number > before_barrier and number % 100 == 0:
            time.sleep(BREATH)

    handler.close()


def rotate_on_signal(path: str, barrier, times: int, generations) -> None:
    """
    Stand in for logrotate: rename the journal, and let a new one appear.

    Renaming and creating the empty file is exactly what ``create`` does in
    ``dockers/logrotate.conf``. Nothing is compressed or deleted, because a
    record missing at the end of the test has to mean the rotation lost it
    and not that a policy removed it.

    Nothing is waited for between the renames beyond a breath: logrotate
    does not ask the writers whether they are mid-record either.

    Args:
        path: The journal being rotated.
        barrier: Met when every writer has records down and more to write.
        times: How many rotations to perform.
        generations: Counter the test reads to know they happened.
    """
    barrier.wait()

    for _ in range(times):
        generations.value += 1
        os.rename(path, f"{path}.{generations.value}")
        Path(path).touch()
        time.sleep(2 * BREATH)
