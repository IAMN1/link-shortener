""" `FLASK_APP` reaches a container without an env file naming it.

The name lives in `.flaskenv`, and it was moved there on purpose: Flask
reads that file before any env file, so `flask <anything>` works whatever a
deployment calls its own configuration. On the host that held. In the image
it did not -- the Dockerfile copied `src`, `alembic.ini` and `migrations`,
and `.flaskenv` was not among them.

Measured on the built image, with no `FLASK_APP` in the environment:

    $ docker run --rm --entrypoint flask link-shortener-app --help
    Error: Could not locate a Flask application. Use the 'flask --app'
    option, 'FLASK_APP' environment variable, or a 'wsgi.py' or 'app.py'
    file in the current directory.

The running stack did not notice, because its env file happens to name
`FLASK_APP` as well -- which is the arrangement the move was made to stop
depending on. A deployment that writes its own env file from the documented
minimum gets a container where no `flask` command runs: no migration, no
`create-admin`, no `db load-base-roles`.

Read from the Dockerfile rather than from a built image. Building one takes
minutes and this has to fail on the edit that removes the line, not on the
day somebody happens to rebuild. What a build would add is that the file is
in the context at all -- and `.dockerignore` failing to exclude it is
checked by `test_build_context_excludes_local_artefacts.py`, from the other
side.
"""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = ROOT / "dockers" / "Dockerfile"
DOCKERIGNORE = ROOT / ".dockerignore"


def _copied():
    """Every source path the Dockerfile copies from the build context."""
    copied = []
    for line in DOCKERFILE.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^COPY\s+(?!--from)(.+?)\s+\S+\s*$", line)
        if match:
            copied.extend(match.group(1).split())
    return copied


class TestTheNameTravelsWithTheImage:

    def test_the_file_exists_to_be_copied(self):
        assert (ROOT / ".flaskenv").exists(), (
            ".flaskenv is gone; FLASK_APP has moved somewhere else and this "
            "check needs rewriting rather than deleting"
        )

    def test_the_dockerfile_copies_it(self):
        # `removeprefix`, not `lstrip`: `lstrip("./")` strips *characters*,
        # so it turns `.flaskenv` into `flaskenv` and the comparison never
        # matches. It cost this file one red run to notice.
        copied = [source.removeprefix("./") for source in _copied()]

        assert ".flaskenv" in copied, (
            f"the image would carry no FLASK_APP: {DOCKERFILE.relative_to(ROOT)} "
            f"copies {copied}"
        )

    def test_the_build_context_does_not_exclude_it(self):
        """
        A `COPY` of an excluded path fails the build loudly, so this is the
        cheaper half of the same guarantee -- and the one that says why.
        """
        patterns = [
            line.strip()
            for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

        for pattern in patterns:
            assert not re.fullmatch(
                pattern.replace(".", r"\.").replace("*", ".*"), ".flaskenv"
            ), f".dockerignore pattern {pattern!r} would keep .flaskenv out"


class TestTheNameIsWhatTheApplicationFactoryIs:
    """
    The file is only worth carrying if it names something that exists: a
    stale module path in it fails the same way a missing file does, and
    reads as a Docker problem rather than a rename nobody finished.
    """

    def test_it_names_the_factory_the_code_defines(self):
        declared = re.search(
            r"^FLASK_APP=(\S+)$",
            (ROOT / ".flaskenv").read_text(encoding="utf-8"),
            re.M,
        )
        assert declared, ".flaskenv no longer sets FLASK_APP"

        module, _, attribute = declared.group(1).partition(":")
        imported = __import__(module, fromlist=[attribute or "__name__"])

        assert hasattr(imported, attribute), (
            f"{module} has no {attribute}, which is what .flaskenv points at"
        )
