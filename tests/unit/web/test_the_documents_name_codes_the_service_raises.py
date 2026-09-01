"""
A published document must not promise an error code the service dropped.

``login`` stopped answering ``EMAIL_NOT_VERIFIED`` -- an unconfirmed
address is now refused exactly as a wrong password is, so the pair cannot
be read as "that password was right". The change reached the code and the
tests, and four places went on promising the old one:

* ``web/schemas/openapi.py``, the document served at ``/api/docs`` and the
  one a client writes its branches against;
* ``README.md`` and ``README.ru.md``, in the endpoint table;
* ``docs/configuration.md``, under ``MAIL_ENABLED``.

Measured on the running service while all four said otherwise::

    POST /api/v1/auth/login  (right password, address unconfirmed)
        -> 401 {"error": "INVALID_CREDENTIALS", ...}
    POST /api/v1/auth/login  (wrong password)
        -> 401 {"error": "INVALID_CREDENTIALS", ...}

Nothing held them. ``test_the_document_declares_what_the_routes_answer``
compares **statuses**, not the codes inside the answers, and
``test_the_translations_carry_the_same_facts`` compares the Russian
document against the English one -- so both README rows agreed with each
other and both were wrong.

What this sweeps for is a name shaped like a code: at least two
``UPPER_CASE`` words joined by underscores. That shape is why ``URL``,
``API`` and ``JSON`` are not swept up, and it is the shape every code in
``STATUS_BY_CODE`` has.
"""

import ast
import pathlib
import re

import pytest

import link_shortener
from link_shortener.web.schemas.openapi import build_openapi


SOURCE = pathlib.Path(link_shortener.__file__).parent
ROOT = SOURCE.parent.parent

DOCUMENTS = [
    ROOT / "README.md",
    ROOT / "README.ru.md",
    ROOT / "docs" / "configuration.md",
]
"""The prose that names error codes to a reader making decisions on them."""

LOOKS_LIKE_A_CODE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")
"""``EMAIL_NOT_VERIFIED``, and not ``URL`` or ``JSON``."""

def _names_that_are_settings() -> set:
    """
    Every shouted name in this project that is a setting, not a code.

    Read from where settings actually live rather than listed here: the
    configuration class, both ``.env`` templates and the compose files.
    A list typed into a test is a list that stops agreeing with the
    project on the day somebody adds a setting, and it would be this test
    that started lying rather than the documents it guards.

    Returns:
        The set of names to ignore when sweeping prose for error codes.
    """
    from link_shortener.infrastructure.configs.app.base import BaseConfig

    names = {name for name in dir(BaseConfig) if name.isupper()}

    for template in (ROOT / ".env.example", ROOT / ".env.docker.example"):
        if template.exists():
            for line in template.read_text(encoding="utf-8").splitlines():
                stripped = line.lstrip("# ").strip()
                if "=" in stripped:
                    names.add(stripped.split("=", 1)[0].strip())

    for compose in (ROOT / "dockers").glob("*.yml"):
        names.update(
            re.findall(r"\$\{([A-Z][A-Z0-9_]*)", compose.read_text(encoding="utf-8"))
        )

    # Constants this project defines anywhere under ``src`` -- the guides
    # name several while explaining how something works, and they are
    # symbols rather than answers a caller can get.
    for path in SOURCE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = (
                    node.targets if isinstance(node, ast.Assign)
                    else [node.target]
                )
                for target in targets:
                    if isinstance(target, ast.Name) and target.id.isupper():
                        names.add(target.id)

    # Files of this repository, which the READMEs link to by name.
    names.update(
        path.stem for path in ROOT.glob("*.md") if path.stem.isupper()
    )

    # Names of the same shape that belong to none of the above:
    # environment variables Flask and the tooling read.
    names.update({
        "FLASK_ENV", "FLASK_DEBUG", "FLASK_RUN_HOST", "FLASK_RUN_PORT",
        "FLASK_RUN_FROM_CLI", "PYTHONPATH", "GITHUB_ENV", "REMOTE_ADDR",
        "X_FORWARDED_FOR", "ALEMBIC_DATABASE_URL", "STATUS_BY_CODE",
        "BEYOND_ADMIN_ALL", "NOT_REACHED_ON_PURPOSE", "DEFAULT_ENV",
        "APP_SRC_PATH", "LOG_HOST_PATH",
    })
    return names


NOT_ERROR_CODES = _names_that_are_settings()
"""Names of that shape which are settings, headers or symbols, not codes."""


def codes_the_source_raises() -> set:
    """
    Every error code spelled out in a ``DomainError`` under ``src``.

    Returns:
        The set of code strings the service can actually answer with.
    """
    found = set()
    for path in sorted(SOURCE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg == "code" and isinstance(
                    keyword.value, ast.Constant
                ):
                    found.add(keyword.value.value)
            name = getattr(node.func, "id", getattr(node.func, "attr", ""))
            if name in ("DomainError", "__init__") and len(node.args) > 1:
                second = node.args[1]
                if isinstance(second, ast.Constant) and isinstance(
                    second.value, str
                ):
                    found.add(second.value)
    return found


def promised_codes(text: str) -> set:
    """
    The error codes a piece of prose names to its reader.

    Args:
        text: The document, or one description out of the API document.

    Returns:
        Every ``UPPER_CASE_WITH_UNDERSCORES`` name that is not a known
        setting or header.
    """
    return {
        name for name in LOOKS_LIKE_A_CODE.findall(text)
        if name not in NOT_ERROR_CODES
    }


class TestTheSweepHasSomethingToSweep:
    """A sweep over nothing passes and proves nothing."""

    def test_the_service_raises_codes(self):
        assert len(codes_the_source_raises()) >= 10

    def test_the_shape_finds_a_code_and_leaves_prose_alone(self):
        found = promised_codes(
            "Answers INVALID_CREDENTIALS, as JSON, over HTTP, for a URL."
        )

        assert found == {"INVALID_CREDENTIALS"}


class TestTheApiDocumentPromisesNothingTheServiceDropped:
    """
    The document a client writes its branches against.

    A caller that reads ``EMAIL_NOT_VERIFIED`` here writes a branch for an
    answer that never comes, and the branch it needs -- telling that
    refusal from a wrong password -- is one the service deliberately no
    longer offers.
    """

    @pytest.fixture(scope="class")
    def described(self):
        """Every response description in the published document."""
        document = build_openapi(base_url="http://localhost:5000")
        out = []
        for path, operations in document["paths"].items():
            for verb, operation in operations.items():
                for status, response in operation.get("responses", {}).items():
                    text = response.get("description", "")
                    if text:
                        out.append((f"{verb.upper()} {path} {status}", text))
        return out

    def test_the_document_describes_its_answers(self, described):
        assert len(described) >= 50

    def test_every_code_it_names_is_one_the_service_raises(self, described):
        raised = codes_the_source_raises()

        promised = {
            where: sorted(promised_codes(text) - raised)
            for where, text in described
            if promised_codes(text) - raised
        }

        assert not promised, (
            "the published document promises codes this service does not "
            f"answer with: {promised}"
        )


class TestThePublishedProseNamesNothingTheServiceDropped:
    """
    The README tables and the settings guide, held to the same rule.

    Both README rows said ``EMAIL_NOT_VERIFIED`` and agreed with each
    other, which is exactly what the translation test checks -- so the
    check that existed could not notice.
    """

    @pytest.mark.parametrize(
        "document", DOCUMENTS, ids=lambda p: p.name
    )
    def test_every_code_it_names_is_one_the_service_raises(self, document):
        raised = codes_the_source_raises()
        text = document.read_text(encoding="utf-8")

        assert document.exists(), document

        promised = sorted(promised_codes(text) - raised)

        assert not promised, (
            f"{document.name} names codes this service does not answer "
            f"with: {promised}"
        )
