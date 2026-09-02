"""Rotation is somebody else's job, and this is what makes that safe.

Nothing in ``infrastructure/logging`` rotates: no ``RotatingFileHandler``,
no ``maxBytes``. That is a decision, not an omission -- four gunicorn
workers write ``application.log`` at once, and a handler that rotates for
itself opens the base file in ``w`` mode while the other three are writing
into it. Measured over 80 000 records through four processes, that
destroyed between 10 and 16 per cent of them; the same load through
``WatchedFileHandler`` with an outside rotation lost none. The write-up is
in ``docs/decisions.md``.

What the application does instead is notice. ``WatchedFileHandler`` stats
the path before each write and reopens when the device or inode it holds is
no longer the one at that name. This file is what says that is still true:

  - a record written after the file was moved aside lands in a new file,
    not in the moved one;
  - the records written before it stay where they were, whole;
  - the plain ``FileHandler`` this could be "simplified" into does the
    opposite, which is the cost of the choice, stated rather than assumed;
  - ``setup_logging`` installs handlers that follow, on all three journals;
  - the configuration shipped in ``dockers/logrotate.conf`` names the same
    three files the application writes.

The last one exists because ``missingok`` makes the failure silent: a
configuration pointed at a name nothing writes rotates nothing, reports
nothing, and leaves the disk filling up exactly as it did before.
"""

import fnmatch
import logging
import os
import re
from pathlib import Path

import pytest

from link_shortener.infrastructure.configs.app.base import JOURNAL_NAME
from link_shortener.infrastructure.configs.app.testing import TestingConfig
from link_shortener.infrastructure.logging.bootstrap import setup_logging
from link_shortener.infrastructure.logging.handlers.raising import (
    RaisingWatchedFileHandler,
)
from link_shortener.infrastructure.logging.logging_settings import LoggingSettings


OWN_LOGGER = "link_shortener.test.rotation"
"""A name this application owns.

``RaisingWatchedFileHandler`` re-raises failed writes only for its own
records, and a write that quietly fails would make every check here pass
over nothing.
"""

SHIPPED_CONFIG = Path(__file__).resolve().parents[4] / "dockers/logrotate.conf"
ENTRYPOINT = (
    Path(__file__).resolve().parents[4] / "dockers/logrotate-entrypoint.sh"
)

JOURNAL_IN_CONFIG = re.compile(
    r"^(/logs/\$\{(\w+)\}\.log)\s*\{?\s*$", re.MULTILINE
)
"""A journal named by the shipped template, and the variable naming it.

Both forms of a logrotate block header are one line: the last path carries
the opening brace, the ones above it stand alone.

The names are variables rather than literals because the rotator resolves
them at start-up from the same three settings the application reads -- see
``dockers/logrotate-entrypoint.sh``. Written literally, they agreed with a
tree that had not touched the defaults and with no deployment that had.
"""


@pytest.fixture
def journal(tmp_path):
    """
    A logger writing one file through the handler the application uses.

    Returns:
        Tuple of the log file path and the logger writing to it.
    """
    path = tmp_path / "application.log"
    log = logging.getLogger(OWN_LOGGER)
    log.handlers.clear()
    log.setLevel(logging.INFO)
    log.propagate = False
    log.addHandler(RaisingWatchedFileHandler(path, encoding="utf-8"))

    yield path, log

    for handler in log.handlers:
        handler.close()
    log.handlers.clear()


def move_aside(path):
    """
    Do to the file what logrotate does: rename it and leave the name free.

    Args:
        path: The journal being rotated.

    Returns:
        Path the old contents now live under.
    """
    rotated = path.with_suffix(".log.1")
    os.rename(path, rotated)
    return rotated


class TestAMovedFileIsNoticed:

    def test_the_record_after_a_rotation_lands_in_a_new_file(self, journal):
        path, log = journal
        log.info("before the rotation")

        move_aside(path)
        log.info("after the rotation")

        assert path.exists(), "the journal was never reopened"
        assert "after the rotation" in path.read_text(encoding="utf-8")

    def test_the_records_before_it_stay_in_the_rotated_file(self, journal):
        path, log = journal
        log.info("before the rotation")

        rotated = move_aside(path)
        log.info("after the rotation")

        kept = rotated.read_text(encoding="utf-8")
        assert "before the rotation" in kept
        # The other half of "it reopened": had it not, this record would
        # have gone here, into a file that the next rotation renames again
        # and the retention policy eventually deletes.
        assert "after the rotation" not in kept

    def test_a_plain_file_handler_writes_into_the_file_that_was_moved(
        self, tmp_path
    ):
        """
        The cost of the choice, stated rather than assumed.

        ``FileHandler`` is the obvious simplification -- it is one class
        simpler and does not stat before every write. It also keeps its
        descriptor on the moved file, so everything written after a
        rotation goes to an archive instead of the journal, and the
        journal at the live name stays empty until the process restarts.
        """
        path = tmp_path / "application.log"
        log = logging.getLogger(f"{OWN_LOGGER}.plain")
        log.handlers.clear()
        log.setLevel(logging.INFO)
        log.propagate = False
        log.addHandler(logging.FileHandler(path, encoding="utf-8"))

        try:
            log.info("before the rotation")
            rotated = move_aside(path)
            log.info("after the rotation")

            assert "after the rotation" in rotated.read_text(encoding="utf-8")
            assert not path.exists()
        finally:
            for handler in log.handlers:
                handler.close()
            log.handlers.clear()


class TestWhatSetupLoggingInstalls:
    """
    The check that matters most, because it guards the seam.

    Everything above is about one handler built by hand. This is about the
    handlers the application actually runs with: swapping the class in
    ``bootstrap.py`` breaks rotation everywhere and breaks no test that
    reads a log file.
    """

    @pytest.fixture(autouse=True)
    def give_back_the_loggers(self):
        """
        Hand back the root and audit loggers.

        ``setup_logging`` clears the root logger's handlers and installs
        its own, and ``logging`` keeps them for the life of the process.
        Left in place, they point at a ``tmp_path`` that pytest removes,
        and every later test writing a log record writes into a deleted
        directory.
        """
        root = logging.getLogger()
        audit = logging.getLogger("audit")
        saved = (
            root.handlers[:], root.level,
            audit.handlers[:], audit.level, audit.propagate,
        )

        yield

        root.handlers[:], root.level = saved[0], saved[1]
        audit.handlers[:], audit.level, audit.propagate = saved[2], saved[3], saved[4]

    def test_every_file_handler_follows_an_outside_rotation(self, tmp_path):
        settings = LoggingSettings(
            log_dir=str(tmp_path),
            log_file_name="application",
            audit_log_filename="audit",
            error_log_filename="error",
            log_date_format="%Y-%m-%d %H:%M:%S",
            log_to_console=False,
            log_to_file=True,
            log_level_str="INFO",
            debug=False,
            sqlalchemy_log_level="WARNING",
            werkzeug_log_level="WARNING",
            logger_type="standard",
        )

        setup_logging(settings)

        writing_to_files = [
            handler
            for handler in logging.getLogger().handlers + logging.getLogger("audit").handlers
            if isinstance(handler, logging.FileHandler)
        ]

        assert len(writing_to_files) == 3, (
            "expected application, error and audit; "
            f"got {[Path(h.baseFilename).name for h in writing_to_files]}"
        )
        for handler in writing_to_files:
            assert isinstance(handler, logging.handlers.WatchedFileHandler), (
                f"{Path(handler.baseFilename).name} is written by "
                f"{type(handler).__name__}, which does not notice a rotation"
            )


class TestTheShippedConfigurationNamesTheseFiles:
    """
    ``dockers/logrotate.conf`` against the names the application writes.

    Nothing else compares them. ``missingok`` is in that configuration on
    purpose -- a deployment with auditing turned off has no ``audit.log``
    and rotation must not fail over it -- and the price is that a
    configuration naming a file nobody writes is indistinguishable from a
    working one until the disk fills up.
    """

    @pytest.fixture(scope="class")
    def variables_in_the_template(self):
        text = SHIPPED_CONFIG.read_text(encoding="utf-8")
        return {variable for _path, variable in JOURNAL_IN_CONFIG.findall(text)}

    def test_it_follows_every_setting_the_application_reads(
        self, variables_in_the_template
    ):
        """The three names, asked for by the same names on both sides.

        A journal the template does not name is a journal nothing rotates,
        and ``missingok`` makes that indistinguishable from a working
        configuration until the disk fills up.
        """
        assert variables_in_the_template == {
            "LOG_FILENAME", "ERROR_LOG_FILENAME", "AUDIT_LOG_FILENAME",
        }

    def test_every_variable_it_names_is_one_the_profile_carries(
        self, variables_in_the_template
    ):
        """A variable spelled wrong resolves to nothing.

        ``envsubst`` puts an empty string where it cannot resolve, so
        ``LOG_FILNAME`` would leave ``/logs/.log`` in the finished config
        -- a path nothing writes, quietly rotated forever.
        """
        config = TestingConfig()

        for variable in variables_in_the_template:
            assert getattr(config, variable, None), variable

    def test_the_rotator_falls_back_to_the_same_defaults(
        self, variables_in_the_template
    ):
        """The entrypoint's defaults against the profile's.

        The rotator cannot read ``BaseConfig``; it is a Debian container
        with a shell script in it. So the three defaults are written twice,
        and this is what keeps the second copy honest -- the same
        arrangement ``logging_settings_from`` is held to.
        """
        script = ENTRYPOINT.read_text(encoding="utf-8")
        config = TestingConfig()

        for variable in variables_in_the_template:
            expected = getattr(config, variable)
            assert f'${{{variable}:-{expected}}}' in script, variable

    def test_the_rotator_admits_exactly_what_the_application_admits(
        self, variables_in_the_template
    ):
        """The two name checks, held against each other on real values.

        The entrypoint says its check "admits and refuses exactly what
        ``JOURNAL_NAME`` in configs/app/base.py does", and until this
        existed nothing held it to that. Both halves were wrong at once.
        The pattern in the configuration was matched with ``re.match``
        against ``^...$``, and "$" in Python also matches just before a
        trailing newline -- which is the shape a value read out of a file
        or a Kubernetes Secret arrives in -- so the application came up on
        ``LOG_FILENAME=application\n`` and this container exited 1 on the
        same value: rotation off, application running, nothing saying so.
        And the script refused only a *leading dot* where the pattern
        requires a leading alphanumeric, so ``_app`` went the other way.

        The shell patterns are read out of the shipped script rather than
        written here, so a change to one side has to be made on both.
        """
        script = ENTRYPOINT.read_text(encoding="utf-8")
        found = re.search(r'case "\$\{name\}" in\n\s*(.+?)\)', script)
        assert found, "the entrypoint no longer refuses a name by a case"

        patterns = [
            piece.strip().strip('"') for piece in found.group(1).split("|")
        ]
        assert patterns, "no patterns to hold the two checks against"

        def the_shell_refuses(name: str) -> bool:
            # The empty pattern is the script's `""` branch, which fnmatch
            # would read as "matches only the empty string" anyway; spelt
            # out so an empty name is refused for a reason a reader sees.
            return not name or any(
                fnmatch.fnmatchcase(name, pattern)
                for pattern in patterns if pattern
            )

        for name in (
            "application", "audit", "error", "A1-b_c.2", "app.log",
            "_app", "-app", ".hidden", "", "a/b", "../etc/cron.d/x",
            "app\n", "app\r\n", "\u043f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u0435",
        ):
            assert the_shell_refuses(name) is not bool(
                JOURNAL_NAME.fullmatch(name)
            ), (
                f"{name!r}: the rotator and the application disagree about "
                f"whether this is a journal name"
            )

    def test_it_names_them_where_the_rotator_mounts_them(self):
        """
        The paths are the container's, not the host's.

        ``docker-compose.yml`` mounts the journals into the rotator at
        ``/logs``. A path written from ``LOG_DIR`` instead would be right
        on the machine it was written on and wrong in the container, and
        ``missingok`` would keep quiet about it.
        """
        text = SHIPPED_CONFIG.read_text(encoding="utf-8")
        found = [path for path, _variable in JOURNAL_IN_CONFIG.findall(text)]

        assert found, "the configuration names no journal at all"
        assert all(path.startswith("/logs/") for path in found), found
