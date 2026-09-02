"""
The two configuration templates declare the same settings, and differ only
where the difference is the point.

``.env.example`` describes a run on the host -- SQLite, the cache in the
process, no queue. ``.env.docker.example`` describes the same service with
every dependency in a container. There are two files because one cannot
answer both questions at once, and the single file that tried said
``COMPOSE_PROFILES=db,cache,broker`` and ``DATABASE_TYPE=sqlite`` on the
same page. Following it brought up PostgreSQL and two Redis, then went past
all three: the migration wrote a schema inside a throwaway container, the
application opened an empty SQLite file beside it, ``/health`` answered
``healthy`` and the landing page answered ``500 no such table: roles``.

Two files buy that back at the usual price -- they drift. So this holds
them together:

* every setting declared in one is declared in the other, so a key added to
  the catalogue cannot reach only the local half;
* their values are identical **except** for the nine named below, so a
  value that changes for the host run cannot silently stay behind in the
  Docker one;
* those nine hold exactly the values written here, so changing the shape
  of the Docker deployment is a change to this file as well -- which is
  what makes it reviewable.

What this deliberately does not check: comments. The two files explain
themselves differently and should.
"""

import re
from pathlib import Path

import pytest


LOCAL = Path(".env.example")
DOCKER = Path(".env.docker.example")

# A declaration is NAME=value at the start of a line, optionally commented
# out -- a commented declaration is how the template offers a setting whose
# default is the right answer (`# DOMAIN=`). The same shape appears inside
# prose in the headers of both files, which is why `_declarations` prefers
# the live line and why a name may be declared live only once.
DECLARATION = re.compile(
    r"^(?P<off>#\s*)?(?P<name>[A-Z][A-Z0-9_]*)=(?P<value>.*)$"
)

# name -> the value the Docker template is expected to carry. Eight, and
# the reason for each is in that file's own header.
DOCKER_DIFFERS = {
    "ENV_FILE": ".env.docker",
    "DATABASE_TYPE": "postgresql",
    "DATABASE_HOST": "db",
    "DATABASE_NAME": "db_shortener",
    "DATABASE_USER": "shortener",
    "REDIS_ENABLED": "true",
    "CELERY_ENABLED": "true",
    "DOMAIN": "localhost:5000",
    # The ninth. The docker template ships `logs` in COMPOSE_PROFILES,
    # which brings up the rotator, and a rotator needs files to rotate --
    # so this half of the pair is stated here rather than left to
    # `FLASK_ENV=development`, whose default is false. The local template
    # ships no profiles that would care, and leaves it to the profile.
    "LOG_TO_FILE": "true",
}


def _declarations(path: Path) -> dict[str, tuple[bool, str]]:
    """
    Every setting the template declares: name -> (commented out, value).

    A name that appears both live and commented out resolves to the live
    one -- both headers quote settings in prose, and a quotation is not a
    declaration. A name that appears live twice is a defect in the template
    itself and is reported as one.
    """
    live: dict[str, tuple[int, str]] = {}
    quiet: dict[str, str] = {}

    for number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        found = DECLARATION.match(line)
        if not found:
            continue
        name, value = found["name"], found["value"].strip()
        if found["off"]:
            quiet.setdefault(name, value)
        else:
            if name in live:
                pytest.fail(
                    f"{path}: {name} is set twice, on lines "
                    f"{live[name][0]} and {number}. The second wins at "
                    f"runtime and the first is read by whoever edits the "
                    f"file, which is how a setting comes to mean two "
                    f"things at once."
                )
            live[name] = (number, value)

    resolved = {name: (False, value) for name, (_, value) in live.items()}
    for name, value in quiet.items():
        resolved.setdefault(name, (True, value))
    return resolved


@pytest.fixture(scope="module")
def local() -> dict[str, tuple[bool, str]]:
    return _declarations(LOCAL)


@pytest.fixture(scope="module")
def docker() -> dict[str, tuple[bool, str]]:
    return _declarations(DOCKER)


class TestBothTemplatesExist:

    def test_the_local_template_is_there(self):
        assert LOCAL.is_file(), f"{LOCAL} is the catalogue every other document points at"

    def test_the_docker_template_is_there(self):
        # It is matched by `.env.*` in .gitignore and needs its own
        # negation to be tracked at all. Without that line the file exists
        # for whoever wrote it and for nobody who clones.
        assert DOCKER.is_file(), (
            f"{DOCKER} is missing. If it is on disk, check .gitignore: "
            f"`.env.*` matches it, and it needs `!{DOCKER}` of its own."
        )


class TestNeitherTemplateHasSettingsTheOtherLacks:

    def test_the_docker_template_declares_nothing_new(self, local, docker):
        invented = sorted(set(docker) - set(local))
        assert not invented, (
            f"{DOCKER} declares {invented}, which {LOCAL} does not. "
            f"{LOCAL} is the exhaustive list every document points at; a "
            f"setting that exists only in the Docker template is one no "
            f"reader of the documentation can find."
        )

    def test_the_docker_template_is_missing_nothing(self, local, docker):
        absent = sorted(set(local) - set(docker))
        assert not absent, (
            f"{DOCKER} is missing {absent}. A setting added to the "
            f"catalogue has to reach both deployments, or the Docker one "
            f"silently keeps a default nobody chose."
        )


class TestTheValuesDifferOnlyWhereTheyShould:

    def test_no_unlisted_value_differs(self, local, docker):
        surprises = {
            name: (local[name][1], docker[name][1])
            for name in sorted(set(local) & set(docker))
            if name not in DOCKER_DIFFERS
            and local[name][1] != docker[name][1]
        }
        assert not surprises, (
            f"These settings differ between the templates and are not in "
            f"the list of nine that may: {surprises}. Either the "
            f"difference is deliberate -- then add it to DOCKER_DIFFERS "
            f"with the reason in {DOCKER}'s header -- or one template was "
            f"edited and the other was not."
        )

    @pytest.mark.parametrize("name,expected", sorted(DOCKER_DIFFERS.items()))
    def test_each_listed_setting_holds_its_value(self, docker, name, expected):
        assert name in docker, f"{DOCKER} no longer declares {name}"
        commented_out, value = docker[name]
        assert value == expected, (
            f"{DOCKER} sets {name}={value!r}, this test expects "
            f"{expected!r}. The Docker path was measured with the value "
            f"here; changing it is a change to the deployment, not a "
            f"typo to be fixed in one place."
        )
        assert not commented_out, (
            f"{DOCKER} has {name} commented out. Every one of the nine is "
            f"a choice this deployment makes rather than a default it "
            f"accepts -- commented out, the value that applies is the "
            f"profile's, which for {name} is what the host run wants."
        )


class TestTheDockerTemplateIsCoherentWithItself:
    """
    The failure that split the templates in two was not a wrong value but a
    pair of values that contradicted each other. These say the pairs agree.
    """

    def test_the_db_profile_and_the_backend_agree(self, docker):
        profiles = docker["COMPOSE_PROFILES"][1].split(",")
        if "db" in profiles:
            assert docker["DATABASE_TYPE"][1] == "postgresql", (
                "COMPOSE_PROFILES brings up PostgreSQL and DATABASE_TYPE "
                "sends the application to SQLite. That combination starts, "
                "reports healthy, and answers 500 to the first request."
            )

    def test_the_cache_profile_and_the_switch_agree(self, docker):
        profiles = docker["COMPOSE_PROFILES"][1].split(",")
        if "cache" in profiles:
            assert docker["REDIS_ENABLED"][1] == "true", (
                "COMPOSE_PROFILES brings up Redis and REDIS_ENABLED leaves "
                "the application with the in-process cache, so the "
                "container runs for nobody and the rate limiter is "
                "per-worker."
            )

    def test_the_broker_profile_and_the_switch_agree(self, docker):
        profiles = docker["COMPOSE_PROFILES"][1].split(",")
        if "broker" in profiles:
            assert docker["CELERY_ENABLED"][1] == "true", (
                "COMPOSE_PROFILES brings up the broker and CELERY_ENABLED "
                "keeps the work inline, so the queue container and the "
                "worker container both run for nobody."
            )

    def test_the_logs_profile_and_the_switch_agree(self, docker):
        """
        The fourth pair, and the one that was shipped broken.

        `logs` brings up the rotator; `LOG_TO_FILE` is what makes the
        files it rotates. The template shipped the profile and left the
        switch to `FLASK_ENV=development`, whose default is false --
        measured on a live walk of that stack: the rotator came up and
        announced "logrotate will follow: application.log, error.log,
        audit.log", the log directory held only its own state file, and
        all three journal pages answered empty for every role entitled
        to read them, on a stack whose journals are a headline feature.
        """
        profiles = docker["COMPOSE_PROFILES"][1].split(",")
        if "logs" in profiles:
            assert docker.get("LOG_TO_FILE", (None, ""))[1] == "true", (
                "COMPOSE_PROFILES brings up the rotator and LOG_TO_FILE "
                "does not write the files it rotates, so the container "
                "runs for nobody and every journal reads empty."
            )

    def test_the_env_file_names_itself(self, docker):
        # compose reads ENV_FILE out of the very file it was given, and
        # hands `../${ENV_FILE}` to the containers. A template that names
        # a different file sends the containers somebody else's settings,
        # or -- more usually -- stops with "env file ... not found".
        assert docker["ENV_FILE"][1] == ".env.docker", (
            "ENV_FILE has to name the file this template is copied to, "
            "because compose passes that name on to the containers."
        )

    def test_no_password_is_shipped(self, docker):
        # The two the stack's own services need are filled by
        # `flask security generate-secrets --write <file>
        # --with-service-passwords`, and both services refuse to start
        # without them. A default here would be a default on every
        # deployment that never edited the line.
        for name in ("DATABASE_PASSWORD", "REDIS_PASSWORD",
                     "SECRET_KEY", "SHORT_CODE_PEPPER"):
            assert docker[name][1] == "", (
                f"{DOCKER} ships a value for {name}. A secret in a tracked "
                f"file is a secret on every deployment that copied it."
            )


NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12,
    # The Russian front page states the same count, and a count nobody
    # reads is a count that goes stale: it said "восемь" while the
    # templates differed by nine.
    "одна": 1, "две": 2, "три": 3, "четыре": 4, "пять": 5, "шесть": 6,
    "семь": 7, "восемь": 8, "девять": 9, "десять": 10,
}
"""Enough to count the settings that differ, spelled as the prose spells them."""

COUNTED_IN_PROSE = [
    # (file, pattern), where group 1 is the number word.
    (DOCKER, r"with (\w+) lines set for a stack"),
    (DOCKER, r"outside the\s*#\s*(\w+) named below"),
    (DOCKER, r"The (\w+) settings that differ"),
    (GUIDE := DOCKER.parent / "docs" / "getting-started.md",
     r"same catalogue as `\.env\.example` with (\w+)\s*\n?>? ?lines set"),
    (GUIDE, r"header lists all (\w+) with the"),
    # The three that were not on this list, and were wrong because of it:
    # both front pages and the template that describes itself. The list is
    # what decides where the count is checked, so a sentence outside it is
    # a sentence nothing reads -- measured, all three said eight while the
    # templates differed by nine, in two languages.
    (DOCKER.parent / "README.md", r"(\w+) lines differ between"),
    (DOCKER.parent / "README.ru.md", r"Различаются (\w+) строк"),
    (DOCKER.parent / ".env.example", r"the same catalogue with (\w+) lines"),
]
"""Every sentence that states how many settings the templates differ by."""


class TestTheProseCountsTheSettingsCorrectly:
    """
    Three sentences in one file said eight while a fourth said nine.

    ``.env.docker.example`` opened with "with **eight** lines set for a
    stack that runs entirely in containers" and "a value differs outside
    the **eight** named below", then listed "The **nine** settings that
    differ from ``.env.example``" fifteen lines further down. Measured, the
    templates differ by nine assignments: ``CELERY_ENABLED``,
    ``DATABASE_HOST``, ``DATABASE_NAME``, ``DATABASE_TYPE``,
    ``DATABASE_USER``, ``DOMAIN``, ``ENV_FILE``, ``LOG_TO_FILE`` and
    ``REDIS_ENABLED`` -- so the guide, which says nine, was right and the
    file describing itself was wrong about itself, twice.

    Nothing noticed, because the drift test above holds the *list* and
    never read the sentence that counts it. The count is the first thing a
    reader meets and the last thing anybody checks.
    """

    @pytest.mark.parametrize(
        "path,pattern", COUNTED_IN_PROSE,
        ids=[f"{p.name}:{i}" for i, (p, _) in enumerate(COUNTED_IN_PROSE)],
    )
    def test_the_number_it_states_is_the_number_that_differ(self, path, pattern):
        import re

        text = path.read_text(encoding="utf-8")
        found = re.search(pattern, text)

        assert found, (
            f"{path.name} no longer carries the sentence this reads "
            f"({pattern!r}). If it was rewritten, point this at the new "
            f"wording rather than dropping the check."
        )
        stated = NUMBER_WORDS.get(found.group(1).lower())
        assert stated is not None, (
            f"{path.name} states {found.group(1)!r}, which is not a number "
            f"this test can read"
        )
        assert stated == len(DOCKER_DIFFERS), (
            f"{path.name} says {found.group(1)} settings differ; "
            f"{len(DOCKER_DIFFERS)} do: {sorted(DOCKER_DIFFERS)}"
        )
