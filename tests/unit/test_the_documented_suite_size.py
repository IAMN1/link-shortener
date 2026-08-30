"""The size of the suite, as published in nine places at once.

The number of collected tests is written into both READMEs (a badge and the
line that runs the suite in each), `CONTRIBUTING.md`, `docs/testing.md`,
`CHANGELOG.md`, `tests/live/browser_test.py` and the CI workflow. Nothing
read any of them, and every one is a copy that can stop being true on its
own.

It had drifted by 64: the suite answered 4291 while all nine said 4227,
including the badge on the front page.

What this can check and what it cannot. The true number is known only to a
run -- collecting the suite from inside itself is a recursion this file will
not start -- so what is held here is that the copies agree with each other
and sit above the floor CI enforces. A release that measures a new number
changes them together or fails here; a number that is stale in all nine at
once is a release-time concern, and `RELEASE-CHECKLIST.md` carries it.

The same for the coverage figure, which lives in two of the same files.
"""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"

SUITE_SIZE = {
    "README.md": (
        r"badge/tests-(\d{4})-",
        r"pytest tests/\s+# (\d{4}) tests",
    ),
    "README.ru.md": (
        r"badge/%D1%82%D0%B5%D1%81%D1%82%D0%BE%D0%B2-(\d{4})-",
        r"pytest tests/\s+# (\d{4}) тестов",
    ),
    "CONTRIBUTING.md": (r"pytest tests/\s+# (\d{4}) tests",),
    "docs/testing.md": (r"\*\*(\d{4}) tests\*\*",),
    "CHANGELOG.md": (r"\*\*Test suite\*\* — (\d{4}) tests",),
    "tests/live/browser_test.py": (r"leaves the suite green at (\d{4})",),
    ".github/workflows/tests.yml": (r"(\d{4}) are collected",),
}
"""Where the number is published, and the shape it is published in.

Written out rather than searched for, so a copy that is deleted or reworded
fails here instead of quietly leaving the set. Each pattern is anchored on
the words around the number: a bare `\\d{4}` would also match a port, a
year, or the floor two lines below it.
"""

COVERAGE = {
    "docs/testing.md": r"\*\*\d{4} tests\*\*, (\d{2}\.\d{2})% coverage",
    "CHANGELOG.md": r"(\d{2}\.\d{2})% statement coverage",
}

FLOOR = r"MINIMUM_TESTS:\s*(\d+)"
COVERAGE_FLOOR = r"--cov-fail-under=(\d+)"


def stated(rel: str, pattern: str) -> int:
    """The number one document publishes, by one pattern."""
    body = (ROOT / rel).read_text(encoding="utf-8")
    found = re.search(pattern, body)

    assert found, f"{rel} no longer states this number: /{pattern}/ found nothing"
    return int(found.group(1))


def percentage(rel: str, pattern: str) -> float:
    """The coverage figure one document publishes."""
    body = (ROOT / rel).read_text(encoding="utf-8")
    found = re.search(pattern, body)

    assert found, f"{rel} no longer states a coverage figure: /{pattern}/"
    return float(found.group(1))


def every_stated_size():
    """(where, number) for every published suite size."""
    return [
        (f"{rel} /{pattern}/", stated(rel, pattern))
        for rel, patterns in SUITE_SIZE.items()
        for pattern in patterns
    ]


class TestTheNineCopiesAgree:

    def test_all_of_them_are_found(self):
        """
        Nine, counted: a pattern that silently stopped matching would make
        the agreement below true of a smaller set.
        """
        assert len(every_stated_size()) == 9

    def test_they_name_one_number(self):
        stated_sizes = every_stated_size()
        numbers = {number for _, number in stated_sizes}

        assert len(numbers) == 1, (
            "the published suite size disagrees with itself:\n  "
            + "\n  ".join(f"{where}: {number}" for where, number in stated_sizes)
        )


class TestTheFloorSitsBelowIt:
    """
    A floor above the suite fails the build for no reason at all, which is
    what the workflow's own comment says it is guarding against.
    """

    def test_the_ci_floor_is_under_the_published_size(self):
        floor = stated(".github/workflows/tests.yml", FLOOR)
        size = every_stated_size()[0][1]

        assert floor < size, f"MINIMUM_TESTS is {floor}, the suite is {size}"

    def test_the_gap_the_workflow_names_is_the_gap_it_has(self):
        """
        The comment states the distance as a figure. It is the number most
        likely to be left behind, because nothing reads a comment.

        It used to be written in words, which this checked by spelling the
        expected number -- and that check could only spell two digits, so
        it skipped once the gap passed a hundred. CI runs the suite under
        `--error-for-skips`, so the skip was not a quiet pass but a failed
        build, and the failure said nothing about the tree.
        """
        floor = stated(".github/workflows/tests.yml", FLOOR)
        size = every_stated_size()[0][1]
        body = WORKFLOW.read_text(encoding="utf-8")

        assert f"The gap is {size - floor}." in body, (
            f"the workflow's comment does not say the gap is {size - floor} "
            f"({size} - {floor})"
        )


class TestTheCoverageFigureAgreesToo:

    def test_both_copies_name_one_figure(self):
        figures = {rel: percentage(rel, pattern) for rel, pattern in COVERAGE.items()}

        assert len(set(figures.values())) == 1, f"coverage disagrees: {figures}"

    def test_it_sits_above_the_floor_pytest_enforces(self):
        toml = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        floor = int(re.search(COVERAGE_FLOOR, toml).group(1))
        figure = percentage("docs/testing.md", COVERAGE["docs/testing.md"])

        assert figure > floor, f"published coverage {figure} is under the floor {floor}"
