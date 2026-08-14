"""
Which ``.env`` a process actually reads.

Looked up from the working directory upwards and nowhere else, a command
started outside the tree -- a celery worker, a bare
``alembic upgrade head`` -- finds none and falls back to the profile
defaults. That is not a loud failure: ``DATABASE_NAME`` became
``db_shortener`` without its extension, ``_sqlite_path`` anchored it under
the project root all the same, and the service came up on a second, empty
database. It surfaced as 401 to anonymous shortening, because the ``guest``
role lived in the other file.

Expectations here are literals. A test that compared the value against
what the configuration reports would agree with whichever file the code
chose to read, including the wrong one.
"""

import pytest

from link_shortener.infrastructure.configs.app import factory as factory_module
from link_shortener.infrastructure.configs.app.factory import ConfigFactory


pytestmark = pytest.mark.usefixtures("detached_env")


def write_env(path, **values):
    """
    Write a ``.env``-style file.

    Args:
        path: File to write.
        **values: Settings to put in it.
    """
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()))


class TestWhereTheFileIsLookedFor:
    """``detached_env`` points the project root at ``tmp_path``."""

    def test_a_worker_outside_the_tree_still_reads_the_root_file(
        self, detached_env, tmp_path_factory, monkeypatch
    ):
        """The defect this closes, in the shape it actually occurred.

        The process stands somewhere with no ``.env`` above it at all --
        which is what ``/tmp`` is for a celery worker -- and would
        otherwise get the profile default.

        The directory it stands in has to be outside the root, not merely
        beside it: a subdirectory has the root above it, so the old walk
        upwards finds the file too and the test passes either way. It did
        -- measured, this test survived a full revert of the fix.
        """
        write_env(detached_env / ".env", GUEST_LINK_LIMIT=41)
        outside = tmp_path_factory.mktemp("outside-the-tree")
        monkeypatch.chdir(outside)

        config = ConfigFactory.create_config("development")

        assert config.GUEST_LINK_LIMIT == 41

    def test_a_line_without_an_equals_sign_does_not_stop_startup(
        self, detached_env
    ):
        """``dotenv_values`` reports such a line as ``None``.

        Publishing that into ``os.environ`` raises ``TypeError: str
        expected, not NoneType`` -- at startup, before anything is served.
        """
        (detached_env / ".env").write_text(
            "GUEST_LINK_LIMIT=41\nA_FLAG_WITH_NO_VALUE\n"
        )

        config = ConfigFactory.create_config("development")

        assert config.GUEST_LINK_LIMIT == 41

    def test_a_directory_named_env_is_not_a_file(
        self, detached_env, tmp_path_factory, monkeypatch
    ):
        """``exists()`` would accept it and skip the fallback.

        ``dotenv_values`` on a directory answers ``{}``, so the settings
        would vanish silently rather than being looked for anywhere else.
        """
        (detached_env / ".env").mkdir()
        outside = tmp_path_factory.mktemp("with-its-own-env")
        write_env(outside / ".env", GUEST_LINK_LIMIT=17)
        monkeypatch.chdir(outside)

        config = ConfigFactory.create_config("development")

        assert config.GUEST_LINK_LIMIT == 17

    def test_the_root_file_wins_over_one_beside_the_caller(
        self, detached_env, monkeypatch
    ):
        """Two files, and the deployment has to get the same one every
        time regardless of where it was started."""
        write_env(detached_env / ".env", GUEST_LINK_LIMIT=41)
        elsewhere = detached_env / "elsewhere"
        elsewhere.mkdir()
        write_env(elsewhere / ".env", GUEST_LINK_LIMIT=17)
        monkeypatch.chdir(elsewhere)

        config = ConfigFactory.create_config("development")

        assert config.GUEST_LINK_LIMIT == 41

    def test_with_no_root_the_walk_from_the_caller_is_all_there_is(
        self, detached_env, monkeypatch
    ):
        """An installed copy has no project directory.

        ``PROJECT_ROOT`` is None there, and inventing one would read a file
        no deployment asked for -- so the previous behaviour has to stay
        exactly as it was.
        """
        monkeypatch.setattr(factory_module, "PROJECT_ROOT", None)
        elsewhere = detached_env / "elsewhere"
        elsewhere.mkdir()
        write_env(elsewhere / ".env", GUEST_LINK_LIMIT=17)
        monkeypatch.chdir(elsewhere)

        config = ConfigFactory.create_config("development")

        assert config.GUEST_LINK_LIMIT == 17

    def test_a_root_without_the_file_falls_back_to_the_walk(
        self, detached_env, monkeypatch
    ):
        """The root is tried first, not exclusively.

        Without the fallback a checkout that keeps no ``.env`` of its own
        would stop reading one the caller does have -- a behaviour change
        nobody asked for, on top of the one that was wanted.
        """
        elsewhere = detached_env / "elsewhere"
        elsewhere.mkdir()
        write_env(elsewhere / ".env", GUEST_LINK_LIMIT=17)
        monkeypatch.chdir(elsewhere)

        config = ConfigFactory.create_config("development")

        assert config.GUEST_LINK_LIMIT == 17
