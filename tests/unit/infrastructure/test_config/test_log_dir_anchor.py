"""
Where log files land.

``LOG_DIR`` defaulted to ``"logs"`` and was handed to the logging setup as
it stood, so it named a different directory for every working directory a
process could be started from -- the same defect already closed for the
database file, left open for the logs beside it. A worker started outside
the tree wrote its logs where nobody looks for them, and nothing said so.

Expectations are literals or independent markers. ``PROJECT_ROOT / value``
as an expectation would pass for any root the code picked, including one
that is wrong.
"""

from pathlib import Path


from link_shortener.infrastructure.configs.app import base as base_module
from link_shortener.infrastructure.configs.app.base import BaseConfig
from link_shortener.infrastructure.configs.app.staging import StagingConfig


def detached(**overrides):
    """
    Build a config that reads its fields from the class, not the machine.

    Args:
        **overrides: Class attributes to set on the subclass.

    Returns:
        An instance detached from the environment (see ``IGNORE_ENV``).
    """
    return type("Detached", (BaseConfig,), {"IGNORE_ENV": True, **overrides})()


class TestARelativeDirectoryIsAnchored:

    def test_the_default_comes_back_absolute(self):
        """``is_absolute`` first: a relative path made of the right pieces
        still points wherever the process happens to stand."""
        log_dir = detached().LOG_DIR

        assert log_dir.startswith("/")
        assert log_dir.endswith("/logs")
        assert log_dir != "logs"

    def test_it_is_anchored_to_the_root_and_not_to_the_caller(
        self, tmp_path, monkeypatch
    ):
        """The distinction the ``is_absolute`` check alone cannot draw.

        Anchoring to ``Path.cwd()`` also produces an absolute path, and
        one that looks right whenever the test runs from the repository
        root -- which is where pytest runs. Standing somewhere else is
        what separates the two.

        The directory it lands in is checked by its markers rather than
        against ``PROJECT_ROOT``: an expectation built from the same
        constant the code reads agrees with whatever root that constant
        holds, a wrong one included: with the root moved one level up, the
        ``PROJECT_ROOT``-shaped assertions all still pass.
        """
        monkeypatch.chdir(tmp_path)

        log_dir = Path(detached().LOG_DIR)

        assert not str(log_dir).startswith(str(tmp_path))
        assert log_dir.name == "logs"
        # `datas/logs`, and the root above that identified by the
        # project's own markers rather than by PROJECT_ROOT, which
        # would agree with any root the code reported.
        assert log_dir.parent.name == "datas"
        assert (log_dir.parent.parent / "pyproject.toml").is_file()
        assert (log_dir.parent.parent / "src").is_dir()

    def test_a_nested_relative_directory_keeps_its_shape(self):
        """``var/log`` is a relative path too, not merely a bare name."""
        log_dir = Path(detached(_default_log_dir="var/log").LOG_DIR)

        assert log_dir.parts[-2:] == ("var", "log")
        assert (log_dir.parent.parent / "pyproject.toml").is_file()


class TestWhatIsLeftAlone:

    def test_an_absolute_directory_is_handed_back_as_it_stands(self):
        """An operator who names a place means that place."""
        assert detached(_default_log_dir="/var/log/mine").LOG_DIR == (
            "/var/log/mine"
        )

    def test_staging_still_writes_where_it_always_did(self):
        """The profile's own default is absolute, and stays untouched."""
        assert StagingConfig().LOG_DIR == "/var/log/link_shortener/staging"

    def test_staging_declares_a_default_and_not_a_field_of_its_own(self):
        """A field there would shadow the property and skip anchoring.

        Asserting only on the absolute default cannot see this: anchoring
        is a no-op on an absolute path, so both spellings answer the same
        thing -- measured, restoring the field left the whole suite green.
        What separates them is a *relative* value set on that profile,
        which a field would hand back untouched.
        """
        relative = type(
            "RelativeStaging", (StagingConfig,),
            {"IGNORE_ENV": True, "_default_log_dir": "staging-logs"},
        )()

        log_dir = Path(relative.LOG_DIR)

        assert log_dir.is_absolute()
        assert log_dir.name == "staging-logs"
        # A profile's own relative default is anchored where it says --
        # straight under the root, not under `datas`, which is only where
        # the base default points.
        assert (log_dir.parent / "pyproject.toml").is_file()

    def test_a_detached_config_does_not_read_the_machine(self, monkeypatch):
        """``IGNORE_ENV`` has to hold for a property as well as a field.

        Reading through ``read_env`` instead of ``read_env_for`` looks
        identical everywhere else in the suite -- nothing exports
        ``LOG_DIR`` -- and quietly reattaches a profile built to be read
        away from its machine.
        """
        monkeypatch.setenv("LOG_DIR", "/var/log/from-the-machine")

        assert detached().LOG_DIR != "/var/log/from-the-machine"
        assert Path(detached().LOG_DIR).name == "logs"

    def test_outside_a_source_tree_nothing_is_invented(self, monkeypatch):
        """An installed copy has no project directory to anchor to.

        Anchoring to something made up would put the logs where no
        deployment asked for them, so the value is passed through -- the
        same rule ``_sqlite_path`` follows.
        """
        monkeypatch.setattr(base_module, "PROJECT_ROOT", None)

        assert detached().LOG_DIR == "datas/logs"
