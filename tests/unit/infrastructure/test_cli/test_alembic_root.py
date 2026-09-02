"""
Which directory ``flask alembic`` runs its subprocess in.

Alembic resolves ``script_location`` from the working directory, so the
answer decides which migrations run -- or whether any do. The search used
to fall back to counting levels up from this module's own file, which is
right in a checkout and wrong everywhere else: the image imports the
package from ``site-packages``, five levels up from there is
``/usr/local/lib/python3.12``, and alembic died with "No 'script_location'
key found" naming neither the directory nor the reason.

``__file__`` is monkeypatched rather than mocked away, because that is the
value the function reads and the only way to stand where an installed copy
stands without installing one.
"""

import subprocess
from pathlib import Path

import pytest

from link_shortener.infrastructure.cli.commands import alembic as alembic_mod
from link_shortener.infrastructure.cli.commands.alembic import (
    AlembicCommands, _project_root
)


class TestFoundFromTheModule:

    def test_the_checkout_answers_with_the_directory_holding_the_file(self):
        """Asserted against the marker, not against a computed path.

        ``result == <something built from __file__>`` would agree with any
        answer the function produced, including a wrong one.
        """
        root = _project_root()

        assert root.is_absolute()
        assert (root / "alembic.ini").is_file()

    def test_it_answers_from_somewhere_with_no_configuration_at_all(
        self, tmp_path, monkeypatch
    ):
        """The module leg, tested where the other leg cannot answer.

        Under pytest the working directory is the repository root, which
        holds an ``alembic.ini`` -- so both legs give the same answer and
        deleting the module leg changes nothing: with the module search
        removed entirely, every other test in this file still passes.
        Standing in an empty directory is what tells them apart.
        """
        monkeypatch.chdir(tmp_path)

        root = _project_root()

        assert (root / "alembic.ini").is_file()
        assert not str(root).startswith(str(tmp_path))


class TestWhatTheSubprocessIsGiven:
    """The point where all of this is actually applied."""

    def test_alembic_runs_in_the_directory_that_was_found(self, monkeypatch):
        """``cwd=None`` passes every test about ``_project_root`` itself.

        ``alembic.ini`` sets ``script_location = migrations`` and
        ``prepend_sys_path = .``, both relative, so the working directory
        of the subprocess decides which migrations run. Nothing checked
        that the found directory ever reached it.
        """
        captured = {}

        def fake_run(args, **kwargs):
            captured.update(kwargs)
            captured["args"] = args
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(alembic_mod.subprocess, "run", fake_run)

        AlembicCommands._run_alembic("current")

        assert captured["cwd"] == str(_project_root())
        assert (Path(captured["cwd"]) / "alembic.ini").is_file()

    def test_a_handoff_left_over_in_the_shell_is_not_passed_on(
        self, monkeypatch
    ):
        """A command with no target must resolve one, not inherit it.

        The variable is what the operator is told to export when a
        migration refuses, and nothing tells them to unset it afterwards.
        Left in place, it silently decides where every later command
        writes -- measured: the migration went to the stale database and
        the intended one was never created, with the same success message
        either way. Nothing held this line.
        """
        captured = {}

        def fake_run(args, **kwargs):
            captured.update(kwargs)
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(alembic_mod.subprocess, "run", fake_run)
        monkeypatch.setenv(
            AlembicCommands.HANDOFF_ENV_VAR, "sqlite:///stale.db"
        )

        AlembicCommands._run_alembic("current")

        assert AlembicCommands.HANDOFF_ENV_VAR not in captured["env"]

    def test_a_target_that_was_given_does_reach_the_subprocess(
        self, monkeypatch
    ):
        """The other half, so that "not passed on" cannot mean "never passed".

        A ``pop`` that ran unconditionally would satisfy the test above and
        leave every ``flask alembic`` command resolving its own database
        again -- which is the defect the handoff exists to prevent.
        """
        captured = {}

        def fake_run(args, **kwargs):
            captured.update(kwargs)
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(alembic_mod.subprocess, "run", fake_run)

        AlembicCommands._run_alembic("current", database_url="sqlite:///a.db")

        assert captured["env"][AlembicCommands.HANDOFF_ENV_VAR] == (
            "sqlite:///a.db"
        )


class TestFoundFromTheWorkingDirectory:

    def test_an_installed_copy_finds_the_operator_s_directory(
        self, tmp_path, monkeypatch
    ):
        """The case the counted fallback got wrong.

        Nothing above the module holds an ``alembic.ini`` -- which is what
        ``site-packages`` looks like -- so the only place left to ask is
        where the operator is standing.
        """
        installed = tmp_path / "site-packages" / "pkg" / "cli"
        installed.mkdir(parents=True)
        monkeypatch.setattr(alembic_mod, "__file__", str(installed / "a.py"))

        project = tmp_path / "deployment"
        project.mkdir()
        (project / "alembic.ini").write_text("[alembic]\n")
        monkeypatch.chdir(project)

        assert _project_root() == project

    def test_a_directory_above_the_caller_counts_too(
        self, tmp_path, monkeypatch
    ):
        """Running from ``migrations/`` is an ordinary thing to do."""
        installed = tmp_path / "site-packages"
        installed.mkdir()
        monkeypatch.setattr(alembic_mod, "__file__", str(installed / "a.py"))

        project = tmp_path / "deployment"
        (project / "migrations").mkdir(parents=True)
        (project / "alembic.ini").write_text("[alembic]\n")
        monkeypatch.chdir(project / "migrations")

        assert _project_root() == project


class TestFoundNowhere:

    def test_it_refuses_instead_of_naming_a_directory_at_random(
        self, tmp_path, monkeypatch
    ):
        """What the level count did instead.

        It always returned something, and that something was a real
        directory -- so the failure surfaced several steps later, out of
        alembic, phrased as a missing configuration key.
        """
        installed = tmp_path / "a" / "b" / "c" / "d" / "e" / "f"
        installed.mkdir(parents=True)
        monkeypatch.setattr(alembic_mod, "__file__", str(installed / "a.py"))

        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.chdir(empty)

        with pytest.raises(FileNotFoundError) as caught:
            _project_root()

        message = str(caught.value)
        assert "alembic.ini" in message
        assert str(installed) in message
        assert str(empty) in message

    def test_a_directory_named_alembic_ini_is_not_a_configuration(
        self, tmp_path, monkeypatch
    ):
        """``exists()`` would accept it and hand alembic a useless path.

        The failure then comes out of alembic as "No 'script_location'
        key found" -- the very message this search exists to prevent.
        """
        installed = tmp_path / "site-packages"
        installed.mkdir()
        monkeypatch.setattr(alembic_mod, "__file__", str(installed / "a.py"))

        project = tmp_path / "deployment"
        (project / "alembic.ini").mkdir(parents=True)
        monkeypatch.chdir(project)

        with pytest.raises(FileNotFoundError):
            _project_root()


WRAPPERS = [
    ("status", lambda: AlembicCommands.status()),
    ("history", lambda: AlembicCommands.history()),
    ("upgrade", lambda: AlembicCommands.upgrade("head")),
    ("downgrade", lambda: AlembicCommands.downgrade("-1")),
    ("migrate", lambda: AlembicCommands.migrate("a message")),
]
"""Every wrapper on the class, and how it is called.

A list rather than a test written per method: the defect below was one
copy of five getting a fix that the other four did not, so a test that
names them one at a time is a test that can be added for one at a time.
"""


class TestAFailureKeepsItsText:
    """What alembic said reaches the operator, whichever command ran.

    Alembic reports a configuration failure on *stdout* with an empty
    stderr -- measured: ``No 'script_location' key found`` arrives there
    with exit 255. ``status`` and ``history`` had been fixed for exactly
    that, and the reason was written down in ``status``; ``upgrade``,
    ``downgrade`` and ``migrate`` still read ``result.stderr`` alone and
    answered a literal ``"Error: "``. ``upgrade`` is what both ``flask
    alembic upgrade`` and ``flask db migrate`` run.
    """

    @pytest.fixture
    def a_root_with_no_migrations(self, tmp_path, monkeypatch):
        """Point the commands at a configuration alembic will refuse."""
        (tmp_path / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")
        monkeypatch.setattr(alembic_mod, "_project_root", lambda: tmp_path)
        return tmp_path

    @pytest.mark.parametrize("name, call", WRAPPERS)
    def test_the_reason_is_reported(
        self, name, call, a_root_with_no_migrations
    ):
        """Not "Error: " on its own, which names nothing."""
        success, output = call()

        assert success is False
        assert "script_location" in output, f"{name} lost the reason: {output!r}"

    @pytest.mark.parametrize("name, call", WRAPPERS)
    def test_the_report_is_never_the_word_error_alone(
        self, name, call, a_root_with_no_migrations
    ):
        """The shape the four broken copies produced, asserted against.

        Kept separate from the check above so that a wrapper which starts
        answering an empty string, rather than the wrong stream, is still
        caught.
        """
        _, output = call()

        assert output.strip() not in ("Error:", "Error"), name


class TestASuccessSaysWhatWasDone:
    """A quiet run still reports, and an upgrade reports what it ran."""

    def test_an_upgrade_carries_alembics_own_account_of_it(self, monkeypatch):
        """Alembic narrates an upgrade on stderr, so both streams are read.

        Without it the report is the same whether eight tables were
        created or nothing was.
        """
        monkeypatch.setattr(
            AlembicCommands,
            "_run_alembic",
            staticmethod(
                lambda *a, **k: subprocess.CompletedProcess(
                    args=list(a),
                    returncode=0,
                    stdout="",
                    stderr="INFO Running upgrade 0001 -> 0002\n",
                )
            ),
        )

        success, output = AlembicCommands.upgrade("head")

        assert success is True
        assert "Running upgrade 0001 -> 0002" in output

    def test_a_run_that_said_nothing_gets_a_sentence(self, monkeypatch):
        """Each wrapper supplies its own, and it is not the other's."""
        monkeypatch.setattr(
            AlembicCommands,
            "_run_alembic",
            staticmethod(
                lambda *a, **k: subprocess.CompletedProcess(
                    args=list(a), returncode=0, stdout="", stderr=""
                )
            ),
        )

        assert AlembicCommands.upgrade("head")[1] == "Migrations applied."
        assert AlembicCommands.downgrade("-1")[1] == "Migrations rolled back."
        assert AlembicCommands.status()[1] == "No migrations applied."
        assert AlembicCommands.history()[1] == "No migration history."
        assert AlembicCommands.migrate("m")[1] == "Migration created."


class TestTheRevisionArgumentReachesAlembic:
    """``history -r <rev>`` narrows the listing, or is silently dropped.

    The option is built into the argument list by a branch nothing ran:
    a wrapper that stopped forwarding it would answer the full history to
    every question, which reads like a correct answer to the wrong one.
    """

    @pytest.fixture
    def recorded(self, monkeypatch):
        """Capture the arguments handed to the subprocess."""
        seen = []

        def remember(*args, **kwargs):
            seen.append(args)
            return subprocess.CompletedProcess(
                args=list(args), returncode=0, stdout="a history", stderr=""
            )

        monkeypatch.setattr(
            AlembicCommands, "_run_alembic", staticmethod(remember)
        )
        return seen

    def test_it_is_forwarded_when_given(self, recorded):
        AlembicCommands.history(revision="0001")

        assert recorded == [("history", "-r", "0001")]

    def test_nothing_is_forwarded_when_it_is_not(self, recorded):
        """No empty ``-r``, which alembic reads as a revision named ""."""
        AlembicCommands.history()

        assert recorded == [("history",)]
