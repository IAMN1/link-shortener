"""
Which file a SQLite deployment actually opens.

``DATABASE_NAME`` is a path for SQLite, and a relative one must not be read
against the working directory of the process: that makes the database's
identity a property of where the operator happens to stand -- the
documented start from the project root opened one file, ``flask`` from
``src/`` created a second, and neither said anything, because SQLite makes
a missing file rather than refusing it.

The expectations here are literals and independent markers rather than
values computed from the configuration -- an assertion built out of
``PROJECT_ROOT`` would agree with any root the code chose to report,
including a wrong one.
"""

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from link_shortener.infrastructure.configs.app.base import (
    PROJECT_ROOT, BaseConfig
)


def detached(**overrides):
    """
    Build a config that reads its fields from the class, not the machine.

    Args:
        **overrides: Class attributes to set on the subclass.

    Returns:
        An instance detached from the environment (see ``IGNORE_ENV``).
    """
    return type("Detached", (BaseConfig,), {"IGNORE_ENV": True, **overrides})()


class TestTheRootItAnchorsTo:

    def test_the_root_is_found_from_the_module_not_from_the_caller(
        self, tmp_path
    ):
        # `PROJECT_ROOT` is computed once, at import, and pytest imports
        # from the repository root -- so a root defined as `Path.cwd()`
        # would hold the right value all through this file and every
        # `chdir` a test does afterwards. That mutation passes everything
        # else while putting the database back beside the caller. Asking
        # the finder again from elsewhere is what tells
        # them apart.
        # Re-imported from elsewhere rather than merely re-invoked: the
        # constant is what the code reads, and calling the finder again
        # would leave a constant assigned from `Path.cwd()` untouched.
        import importlib

        import link_shortener.infrastructure.configs.app.base as base

        here = os.getcwd()
        try:
            os.chdir(tmp_path)
            found = importlib.reload(base).PROJECT_ROOT
        finally:
            os.chdir(here)
            # Back to the module every other test holds a reference to.
            importlib.reload(base)

        assert found is not None, "the root was lost by moving the caller"
        assert (found / "pyproject.toml").is_file()

    def test_the_project_root_is_where_the_project_is(self):
        # The root is found by marker rather than by counting levels, and
        # these two names are the markers it looks for. Checked as
        # literals: pyproject.toml sits at the root and nowhere else in
        # the tree, and src/ is the package directory.
        assert (PROJECT_ROOT / "pyproject.toml").is_file()
        assert (PROJECT_ROOT / "src" / "link_shortener").is_dir()

    def test_both_markers_are_required_not_either_of_them(self, tmp_path):
        # A stray pyproject.toml above an installed copy is an ordinary
        # thing to find -- third-party packages ship one -- and accepting
        # it alone makes that directory the root, so the database lands
        # somewhere no deployment named. Asserted through the finder
        # rather than through the constant, which is fixed at import.
        from link_shortener.infrastructure.configs.app.base import (
            _find_project_root,
        )

        stray = tmp_path / "stray"
        (stray / "pkg" / "deep").mkdir(parents=True)
        (stray / "pyproject.toml").write_text("[project]\n")

        module = stray / "pkg" / "deep" / "base.py"
        module.write_text("")

        import link_shortener.infrastructure.configs.app.base as base

        original = base.__file__
        try:
            base.__file__ = str(module)
            assert _find_project_root() is None
        finally:
            base.__file__ = original


class TestWhatGetsAnchored:

    @pytest.mark.parametrize(
        "name",
        [
            "db_shortener.db",
            # The shipped default, and it carries no extension. Anchoring
            # only names ending in ".db" therefore leaves the default
            # configuration reading from the working directory again --
            # and passed every other test here.
            "db_shortener",
        ],
    )
    def test_a_relative_name_becomes_a_path_under_the_project_root(
        self, name
    ):
        url = detached(DATABASE_NAME=name).get_database_url()

        # Four slashes, which is how SQLAlchemy spells an absolute path:
        # "An absolute path, which is denoted by starting with a slash,
        # means you need four slashes".
        assert url.startswith("sqlite:////")

        opened = Path(url.replace("sqlite:///", "", 1))
        assert opened.is_absolute()
        assert opened.name == name
        # The directory it lands in is identified by the project's own
        # marker rather than by comparing against PROJECT_ROOT again.
        assert (opened.parent / "pyproject.toml").is_file()

    def test_a_name_with_directories_in_it_keeps_them(self):
        # ``.env.example`` calls this setting a path to the database file,
        # so a nested one is a documented value. Anchoring by taking only
        # the final component -- or refusing to anchor anything holding a
        # slash -- passes every other test here: measured, both left the
        # suite green while quietly changing which file is opened.
        url = detached(DATABASE_NAME="data/app.db").get_database_url()

        opened = Path(url.replace("sqlite:///", "", 1))
        # Absolute first: without it the checks below pass on an
        # un-anchored `data/app.db`, since `.parent.parent` of a relative
        # path is the working directory -- which, under pytest, is the
        # project root and holds the marker.
        assert opened.is_absolute()
        assert opened.parent.name == "data"
        assert (opened.parent.parent / "pyproject.toml").is_file()

    def test_the_engine_opens_the_file_under_the_root_from_anywhere(
        self, tmp_path
    ):
        # Comparing the URL from two directories would prove nothing: the
        # relative form reads the same everywhere, and what moved was the
        # file it resolved to. So this opens the database for real, from a
        # directory that is not the root, and looks at where the file
        # landed. Read against the working directory it lands in the
        # caller's directory, and SQLite creates it there without a word.
        probe = "db_anchor_probe.db"
        config = detached(DATABASE_NAME=probe)
        here = os.getcwd()
        engine = None
        try:
            os.chdir(tmp_path)
            engine = create_engine(config.get_database_url())
            engine.connect().close()

            assert not (tmp_path / probe).exists(), (
                "the database was opened beside the caller"
            )
            # Located from the URL and identified by the project's own
            # marker. `PROJECT_ROOT / probe` would have agreed with any
            # root the code reported: measured, both a root one level too
            # high and one level too low passed that way.
            opened = Path(
                config.get_database_url().replace("sqlite:///", "", 1)
            )
            assert opened.is_file()
            assert (opened.parent / "pyproject.toml").is_file()
        finally:
            if engine is not None:
                engine.dispose()
            os.chdir(here)
            if PROJECT_ROOT is not None:
                (PROJECT_ROOT / probe).unlink(missing_ok=True)

    def test_an_absolute_name_is_left_alone(self):
        # Already says where it is. There is no guard for this in the code
        # and none is needed -- joining an absolute path onto a directory
        # yields the absolute path -- so what this holds is the day
        # someone assembles the path by concatenating strings instead.
        config = detached(DATABASE_NAME="/var/lib/shortener/live.db")

        assert config.get_database_url() == (
            "sqlite:////var/lib/shortener/live.db"
        )

    def test_outside_a_source_tree_the_name_is_left_as_given(
        self, monkeypatch
    ):
        # What the built image is: the package is installed into
        # site-packages and copied into the runtime stage, so the module
        # that runs there has no project directory above it at all.
        # Anchoring by counting levels instead of by marker put the file
        # in /usr/local/lib/python3.12 and the connection failed with
        # "unable to open database file" -- measured on a built image.
        # With no root, the name is handed on exactly as every release
        # before this one handed it on.
        import link_shortener.infrastructure.configs.app.base as base

        monkeypatch.setattr(base, "PROJECT_ROOT", None)

        config = detached(DATABASE_NAME="db_shortener.db")

        assert config.get_database_url() == "sqlite:///db_shortener.db"

    def test_the_in_memory_database_is_left_alone(self):
        # Not a file, and every test configuration in this suite uses it.
        config = detached(DATABASE_NAME=":memory:")

        assert config.get_database_url() == "sqlite:///:memory:"

    def test_an_explicit_url_wins_untouched(self):
        # Someone who writes the URL by hand has said what they mean,
        # relative path and all.
        config = detached(DATABASE_URL="sqlite:///beside-the-caller.db")

        assert config.get_database_url() == "sqlite:///beside-the-caller.db"

    def test_postgresql_is_not_touched_by_any_of_this(self):
        # DATABASE_NAME is a database name there, not a path, and a root
        # in front of it would be nonsense. Read against the whole URL:
        # "ends with /shortener" is also true of
        # ".../link-shortener/shortener", so anchoring the postgres branch
        # too would have passed that check.
        config = detached(
            DATABASE_TYPE="postgresql",
            DATABASE_USER="user",
            DATABASE_PASSWORD="pass",
            DATABASE_HOST="db.internal",
            DATABASE_PORT=5432,
            DATABASE_NAME="shortener",
        )

        assert config.get_database_url() == (
            "postgresql+psycopg://user:pass@db.internal:5432/shortener"
        )


class TestNamesThatOpenSomethingElse:
    """``validate`` refuses the two shapes anchoring cannot make safe."""

    def test_a_question_mark_is_refused(self):
        """``a?b.db`` creates and opens a file called ``a``.

        The loss happens in the URL round trip, not in SQLite:
        ``make_url("sqlite:///a?b.db").database`` is ``"a"``, while
        ``sqlite3.connect("a?b.db")`` creates the file that was named. So
        the setting and the file on disk are different things -- and the
        file that appears is empty, which the service treats as a database
        with nothing in it rather than as an error.
        """
        config = detached(DATABASE_NAME="a?b.db", DEBUG=True)

        with pytest.raises(ValueError, match=r"must not contain '\?'"):
            config.validate()

    def test_climbing_out_of_the_root_is_refused(self):
        """``..`` is what turns the anchor into a suggestion."""
        config = detached(DATABASE_NAME="../outside.db", DEBUG=True)

        with pytest.raises(ValueError, match=r"must not contain '\.\.'"):
            config.validate()

    def test_climbing_out_from_further_in_is_refused_too(self):
        """``..`` need not be the first component to leave the root.

        A check written as ``startswith("../")`` passes this one, and
        ``data/../../outside.db`` resolves one level above the project --
        which is the whole thing being prevented.
        """
        config = detached(DATABASE_NAME="data/../../outside.db", DEBUG=True)

        with pytest.raises(ValueError, match=r"must not contain '\.\.'"):
            config.validate()

    def test_a_name_that_merely_contains_two_dots_is_allowed(self):
        """``my..db`` climbs nowhere.

        Checking for the substring rather than for a path component would
        refuse this one -- a refusal an operator cannot act on, because
        nothing about the name is actually wrong.
        """
        detached(DATABASE_NAME="my..db", DEBUG=True).validate()

    def test_a_subdirectory_is_still_allowed(self):
        """For SQLite the name is a path, so ``/`` means what it says."""
        detached(DATABASE_NAME="var/db_shortener.db", DEBUG=True).validate()

    def test_memory_is_not_a_path_and_is_left_alone(self):
        """Every test configuration in the suite uses it."""
        detached(DATABASE_NAME=":memory:", DEBUG=True).validate()

    def test_postgresql_keeps_its_own_stricter_rule(self):
        """``/`` is legitimate in a file path and never in a database
        name, so the two branches cannot share one list."""
        config = detached(
            DATABASE_TYPE="postgresql",
            DATABASE_USER="user",
            DATABASE_PASSWORD="pass",
            DATABASE_HOST="db.internal",
            DATABASE_NAME="var/shortener",
            DEBUG=True,
        )

        with pytest.raises(ValueError, match=r"must not contain '/'"):
            config.validate()
