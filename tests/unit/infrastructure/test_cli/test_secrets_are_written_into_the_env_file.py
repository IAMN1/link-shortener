"""
Tests that `generate-secrets --write` edits an env file rather than a copy.

The printed form of the command is why the setup guide breaks in the
middle: every other step is a command, and this one asks for a text
editor. Writing the values removes that break, so the file has to come
out of it usable -- the same variables, in the same places, with the
comments that explain them still attached.

What is guarded here is mostly what must *not* happen. A rewritten
``SECRET_KEY`` signs out every session and voids every issued token; a
rewritten ``SHORT_CODE_PEPPER`` changes the code a URL not yet shortened
will get. Neither may follow from a setup command being run twice.

Not "stops the codes already handed out from resolving", which is what
this said: a link is resolved by looking its stored code up, and nothing
recomputes one. ``cli/commands/security.py`` retracts that sentence with
a measurement -- a code made under one pepper answered 302 from a process
running another -- and ``_COST_OF_REPLACING``, which is the text an
operator actually reads, says the opposite of what this docstring said.
"""

import os

import pytest

from link_shortener.infrastructure.cli.commands.security import write_secrets


TEMPLATE = """\
# Signs JWTs, sessions and cache entries
SECRET_KEY=
OTHER=untouched
# Salts the short codes
SHORT_CODE_PEPPER=
"""


@pytest.fixture
def env_file(tmp_path):
    """An env template with both secrets present and empty."""
    path = tmp_path / ".env"
    path.write_text(TEMPLATE, encoding="utf-8")
    return path


class TestFillingInAnEmptyTemplate:

    def test_both_values_are_written(self, env_file):
        written = write_secrets(env_file)
        text = env_file.read_text(encoding="utf-8")

        assert f"SECRET_KEY={written['SECRET_KEY']}" in text
        assert f"SHORT_CODE_PEPPER={written['SHORT_CODE_PEPPER']}" in text

    def test_the_two_values_differ(self, env_file):
        """One value used twice would tie the codes to the session key."""
        written = write_secrets(env_file)

        assert written["SECRET_KEY"] != written["SHORT_CODE_PEPPER"]
        # 32 random bytes, hex-encoded, as the printed form has always
        # produced. A short value here would be a downgrade nothing else
        # would notice.
        assert len(written["SECRET_KEY"]) == 64

    def test_everything_else_is_left_alone(self, env_file):
        """
        The file is a template full of comments explaining each variable.

        Rewriting it from a dict of names and values would drop them, and
        the reader would be left with a working file that no longer says
        what anything in it is for.
        """
        write_secrets(env_file)
        lines = env_file.read_text(encoding="utf-8").splitlines()

        assert lines[0] == "# Signs JWTs, sessions and cache entries"
        assert lines[2] == "OTHER=untouched"
        assert lines[3] == "# Salts the short codes"
        assert len(lines) == 5, "the file grew or lost a line"

    def test_a_name_the_file_lacks_is_appended(self, tmp_path):
        path = tmp_path / ".env"
        path.write_text("OTHER=1\n", encoding="utf-8")

        written = write_secrets(path)
        text = path.read_text(encoding="utf-8")

        assert text.startswith("OTHER=1\n")
        assert f"SECRET_KEY={written['SECRET_KEY']}\n" in text
        assert f"SHORT_CODE_PEPPER={written['SHORT_CODE_PEPPER']}\n" in text

    def test_a_file_that_ends_without_a_newline_is_not_glued_together(
        self, tmp_path
    ):
        """``OTHER=1SECRET_KEY=...`` is what the naive append produces."""
        path = tmp_path / ".env"
        path.write_text("OTHER=1", encoding="utf-8")

        write_secrets(path)
        lines = path.read_text(encoding="utf-8").splitlines()

        assert lines[0] == "OTHER=1"


class TestRefusingToOverwriteWhatIsAlreadyThere:

    def test_a_second_run_is_refused(self, env_file):
        write_secrets(env_file)
        before = env_file.read_text(encoding="utf-8")

        with pytest.raises(ValueError) as refusal:
            write_secrets(env_file)

        assert "SECRET_KEY" in str(refusal.value)
        assert env_file.read_text(encoding="utf-8") == before, (
            "the refusal still changed the file"
        )

    def test_force_replaces_them(self, env_file):
        first = write_secrets(env_file)

        second = write_secrets(env_file, force=True)

        assert second["SECRET_KEY"] != first["SECRET_KEY"]
        assert first["SECRET_KEY"] not in env_file.read_text(encoding="utf-8")

    def test_one_value_set_and_one_empty_is_still_a_refusal(self, tmp_path):
        """
        Half a file is the case a "fill in what is missing" rule gets wrong.

        Filling the empty one and leaving the other would hand back a file
        whose two secrets came from different runs -- which is fine -- but
        it would do it silently, on a file somebody had already edited.
        """
        path = tmp_path / ".env"
        path.write_text("SECRET_KEY=already\nSHORT_CODE_PEPPER=\n",
                        encoding="utf-8")

        with pytest.raises(ValueError):
            write_secrets(path)

    def test_a_missing_file_says_so(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            write_secrets(tmp_path / "nothing-here")


class TestThePathsThatAreNotAWritableFile:
    """What an operator hits before the file is ever parsed.

    Both reached them as a traceback or as a wrong sentence: the command
    caught ``FileNotFoundError`` and ``ValueError`` only, so a ``.env``
    owned by root -- the ordinary case on a deployed host -- came out as
    a ``PermissionError`` with an empty error stream, and a directory was
    reported as not existing.
    """

    def test_a_directory_is_not_reported_as_missing(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="is not a file"):
            write_secrets(tmp_path)

    def test_a_path_that_is_really_absent_still_says_so(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="does not exist"):
            write_secrets(tmp_path / "absent.env")

    def test_a_file_that_cannot_be_written_raises_an_os_error(self, tmp_path):
        """Left as ``OSError`` for the caller to render.

        The command turns it into a sentence on stderr; what matters here
        is that it is the kind of error the command catches, rather than
        one that travels past it.
        """
        locked = tmp_path / "locked.env"
        locked.write_text("SECRET_KEY=\n", encoding="utf-8")
        os.chmod(locked, 0o444)
        try:
            with pytest.raises(OSError):
                write_secrets(locked)
        finally:
            os.chmod(locked, 0o644)


DOCKER_TEMPLATE = """\
# Signs JWTs, sessions and cache entries
SECRET_KEY=
OTHER=untouched
# Salts the short codes
SHORT_CODE_PEPPER=
# What the stack's own PostgreSQL is started with
DATABASE_PASSWORD=
# What both Redis are started with
REDIS_PASSWORD=
"""


@pytest.fixture
def docker_env_file(tmp_path):
    """An env template shaped like `.env.docker.example`: four empty names."""
    path = tmp_path / ".env.docker"
    path.write_text(DOCKER_TEMPLATE, encoding="utf-8")
    return path


class TestTheServicePasswordsAreOptedInto:
    """
    The stack's own PostgreSQL and Redis refuse to start without a
    password, and the repository ships none -- so the setup command has to
    be able to produce them. It does not do so by default: a run on the
    host has neither service, and two more secrets in a file that never
    needed them is two more things to keep out of a paste.
    """

    def test_by_default_only_the_two_application_secrets_are_written(
        self, docker_env_file
    ):
        written = write_secrets(docker_env_file)

        assert set(written) == {"SECRET_KEY", "SHORT_CODE_PEPPER"}
        body = docker_env_file.read_text(encoding="utf-8")
        assert "DATABASE_PASSWORD=\n" in body
        assert "REDIS_PASSWORD=\n" in body

    def test_the_flag_adds_the_two_service_passwords(self, docker_env_file):
        written = write_secrets(docker_env_file, with_service_passwords=True)

        assert set(written) == {
            "SECRET_KEY",
            "SHORT_CODE_PEPPER",
            "DATABASE_PASSWORD",
            "REDIS_PASSWORD",
        }

    def test_all_four_reach_the_file(self, docker_env_file):
        written = write_secrets(docker_env_file, with_service_passwords=True)

        body = docker_env_file.read_text(encoding="utf-8")
        for name, value in written.items():
            assert f"{name}={value}\n" in body

    def test_the_four_values_differ(self, docker_env_file):
        written = write_secrets(docker_env_file, with_service_passwords=True)

        assert len(set(written.values())) == 4

    def test_the_service_passwords_survive_a_url(self, docker_env_file):
        # They are carried inside DATABASE_URL and REDIS_URL. A character
        # that has to be percent-encoded there turns a working password
        # into an address the driver cannot parse, and the failure lands
        # at connect time rather than at generation time.
        written = write_secrets(docker_env_file, with_service_passwords=True)

        for name in ("DATABASE_PASSWORD", "REDIS_PASSWORD"):
            assert not set(written[name]) - set(
                "abcdefghijklmnopqrstuvwxyz"
                "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            ), f"{name} carries a character that needs encoding in a URL"

    def test_everything_else_is_still_left_alone(self, docker_env_file):
        write_secrets(docker_env_file, with_service_passwords=True)

        body = docker_env_file.read_text(encoding="utf-8")
        assert "OTHER=untouched\n" in body
        assert "# What both Redis are started with\n" in body

    def test_a_second_run_names_the_cost_of_each_value(self, docker_env_file):
        write_secrets(docker_env_file, with_service_passwords=True)

        with pytest.raises(ValueError) as refusal:
            write_secrets(docker_env_file, with_service_passwords=True)

        said = str(refusal.value)
        # The cost is not the same for the four, and a refusal that
        # described them all as "signs out every session" would be wrong
        # about half of what it lists -- and a refusal that misdescribes
        # the damage is one an operator overrides without reading it.
        assert "signs out every session" in said
        assert "the volume keeps the password it was initialised with" in said
        assert "both Redis still expecting the old one" in said

    def test_force_replaces_the_service_passwords_too(self, docker_env_file):
        first = write_secrets(docker_env_file, with_service_passwords=True)
        second = write_secrets(
            docker_env_file, force=True, with_service_passwords=True
        )

        assert first["DATABASE_PASSWORD"] != second["DATABASE_PASSWORD"]
        assert first["REDIS_PASSWORD"] != second["REDIS_PASSWORD"]
