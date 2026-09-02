"""The Celery worker writes the same journals, and fails differently.

``setup_logging`` used to have one caller, ``create_app``, and a worker
never goes through it. With ``LOG_TO_FILE=true`` the web processes wrote
``application.log``, ``error.log`` and ``audit.log`` and the worker wrote
none of them: what a task logged -- including the failure of one -- existed
only in the container's standard output. Measured before the fix, by
starting a real worker against a dead broker with a log directory of its
own: three connection failures reported, and not one file created.

Two things make it work, and each has a check here.

``celery.signals.setup_logging`` is connected to. That is Celery's
documented way of saying "logging is configured elsewhere": with a
receiver on it Celery leaves the root logger alone, and without one it
installs its own handlers over ours.

And the worker's handlers do not re-raise a failed write, where the web
application's do. Raising is not a good thing in itself -- it exists to
feed ``FailoverService``, which catches it and moves the work to the other
logger. There is no such service behind the module loggers a task uses, so
a raised write there is caught by nothing: a full disk would stop being a
lost log line and start being a failed task.
"""

import importlib
import logging
from pathlib import Path

import pytest

from link_shortener.infrastructure.logging.bootstrap import setup_logging
from link_shortener.infrastructure.logging.handlers.raising import (
    RaisingWatchedFileHandler,
)
from link_shortener.infrastructure.logging.logging_settings import (
    attribute_reader, logging_settings_from,
)
# By name, through importlib, because the ordinary import forms do not
# reach it: `task_queue/__init__.py` does `from .celery_app import
# celery_app`, which rebinds the package attribute from the module to the
# Celery instance inside it. Both `from ... import celery_app` and
# `import ....celery_app as worker` then hand back the instance, and
# monkeypatching `get_config` on it fails with "has no attribute".
worker = importlib.import_module(
    "link_shortener.infrastructure.task_queue.celery_app"
)


class ConfigurationObject:
    """A profile, in the shape the worker reads one: attributes."""

    LOGGING_ENABLED = True
    AUDIT_ENABLED = True
    LOG_TO_FILE = True
    LOG_TO_CONSOLE = False
    LOG_LEVEL = "INFO"
    LOG_FILENAME = "application"
    AUDIT_LOG_FILENAME = "audit"
    ERROR_LOG_FILENAME = "error"
    LOGGER_TYPE = "standard"

    def __init__(self, log_dir):
        self.LOG_DIR = str(log_dir)


@pytest.fixture(autouse=True)
def give_back_the_loggers():
    """
    Hand back the root and audit loggers.

    Both functions under test install handlers on loggers that live for the
    whole process, pointing at a ``tmp_path`` pytest then removes.
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


def file_handlers():
    """
    Every handler writing a file, across both loggers that carry them.

    Returns:
        List of handlers.
    """
    return [
        handler
        for handler in (
            logging.getLogger().handlers + logging.getLogger("audit").handlers
        )
        if isinstance(handler, logging.FileHandler)
    ]


class TestTheWorkerConfiguresLoggingAtAll:

    def test_celery_is_told_that_logging_is_configured_elsewhere(self):
        """
        Without a receiver on this signal, Celery configures the root
        logger itself and the settings below are overwritten by it.
        """
        assert worker.celery_is_configuring_logging.has_listeners()

    def test_it_writes_the_three_journals_the_application_writes(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(
            worker, "get_config", lambda: ConfigurationObject(tmp_path)
        )

        worker.configure_logging()

        assert sorted(Path(handler.baseFilename).name for handler in file_handlers()) == [
            "application.log", "audit.log", "error.log",
        ]

    def test_a_failed_write_does_not_reach_the_task(self, tmp_path, monkeypatch):
        """
        The one difference from the web process, and the reason this is
        not simply ``create_app``'s call in another place.
        """
        monkeypatch.setattr(
            worker, "get_config", lambda: ConfigurationObject(tmp_path)
        )

        worker.configure_logging()

        for handler in file_handlers():
            assert isinstance(handler, logging.handlers.WatchedFileHandler), (
                "a rotation still has to be followed here"
            )
            assert not isinstance(handler, RaisingWatchedFileHandler), (
                f"{Path(handler.baseFilename).name} would raise into a task, "
                "and nothing behind a task catches it"
            )


class TestTheWebProcessStillRaises:
    """The default is unchanged, and that is worth a check of its own."""

    def test_its_file_handlers_re_raise_a_failed_write(self, tmp_path):
        settings = logging_settings_from(
            attribute_reader(ConfigurationObject(tmp_path))
        )

        setup_logging(settings)

        assert file_handlers()
        for handler in file_handlers():
            assert isinstance(handler, RaisingWatchedFileHandler)


class TestBothProcessesReadOneListOfNames:
    """
    The settings were built twice, from two literal lists of the same
    fourteen names -- one in ``create_app``, one that would have been
    written for the worker. Two such lists drift, and the drift is silent:
    the worker keeps logging by a default nobody chose.
    """

    def test_a_mapping_and_an_object_give_the_same_settings(self, tmp_path):
        config = ConfigurationObject(tmp_path)
        as_mapping = {
            name: getattr(config, name)
            for name in dir(config)
            if name.isupper()
        }

        from_object = logging_settings_from(attribute_reader(config))
        from_mapping = logging_settings_from(as_mapping.get)

        assert vars(from_object) == vars(from_mapping)

    def test_it_reads_the_names_the_configuration_publishes(self, tmp_path):
        settings = logging_settings_from(
            attribute_reader(ConfigurationObject(tmp_path))
        )

        assert settings.log_dir == str(tmp_path)
        assert settings.log_file_name == "application"
        assert settings.audit_log_filename == "audit"
        assert settings.error_log_filename == "error"
        assert settings.log_level_str == "INFO"
        assert settings.log_to_file is True
        assert settings.log_to_console is False
        assert settings.logger_type == "standard"
        assert settings.raise_on_write_failure is True
