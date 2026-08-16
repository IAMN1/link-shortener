"""
The sizes of the live runs, as published against as enforced.

Neither live run is collected by pytest -- they are scripts, driven by hand
and by CI -- and each carries a guard of its own: "everything passed" is a
statement about the checks that ran, so both compare what ran against a
number written beside them and fail on a mismatch. Emptying a table of
pages once removed thirteen checks and printed a green run and exit 0.

That closes one half. The other half was open: those numbers are repeated
in six documents, and nothing read any of them. A run that grew from 118
to 123 checks left five documents saying 118, and the drift was found by
eye or not at all -- which is how a reader ends up trusting a number that
was true two months ago.

So the chain is: the live run itself says *constant equals what ran*, and
this file says *documents equal the constant*. Neither can be dropped for
the other. This one is a unit test because it reads files rather than
sending requests -- running the live runs here would take a minute apiece
and need a mail catcher on a port.

Read out of the scripts by ``ast``, never by importing them: importing
``smoke_test`` builds an application, seeds a database, starts an SMTP
catcher and executes all 123 checks at module scope, which is not
something a unit test may do on the way to reading one integer.
"""

import ast
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]

SMOKE = ROOT / "tests/live/smoke_test.py"
BROWSER = ROOT / "tests/live/browser_test.py"

DOCUMENTS = (
    "CONTRIBUTING.md",
    "README.md",
    "README.ru.md",
    "docs/testing.md",
    ".github/workflows/tests.yml",
)
"""Every file that states how big the live runs are.

Listed rather than discovered by a walk of the repository: a document that
stops mentioning the numbers should make this list wrong and visible, not
quietly drop out of a glob.
"""

COUNT = re.compile(
    r"(\d+)\s*(?:checks|проверок|проверки|проверка)\b"
)
"""A count of checks, in either language.

Anchored on the noun rather than on the number, so "2787 tests" and a port
number are not swept in. Both grammatical forms of the Russian are listed
because the plural changes with the number: 123 проверки, 21 проверка.
"""

FRACTION = re.compile(r"\b(\d+)/(\d+)\b")
"""A "how many of them noticed" measurement -- ``81/123``, ``10/21``.

Only the denominator is a published size. The numerator is the result of
its own measurement (breaking `VERIFY_PATH` and counting what reddened)
and nothing here can check it.
"""


def literal_in(path, name):
    """
    Read an integer assigned to ``name`` in a script, without running it.

    Args:
        path: The script to read.
        name: Variable name to find, at module scope or inside a function.

    Returns:
        The integer it is assigned.

    Raises:
        AssertionError: If the name is not assigned exactly one integer.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))

    found = [
        node.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, int)
        for target in node.targets
        if isinstance(target, ast.Name) and target.id == name
    ]

    assert len(found) == 1, (
        f"expected one `{name} = <int>` in {path.name}, found {found}"
    )
    return found[0]


@pytest.fixture(scope="module")
def sizes():
    """
    What the two runs say about themselves.

    Returns:
        Set of the published sizes, which is what a document may name.
    """
    return {
        literal_in(SMOKE, "EXPECTED_CHECKS"),
        literal_in(BROWSER, "expected"),
    }


def counts_in(document):
    """
    Every count of checks a document states.

    Args:
        document: Repository-relative path.

    Returns:
        List of the integers found.
    """
    text = (ROOT / document).read_text(encoding="utf-8")
    return [int(found) for found in COUNT.findall(text)]


class TestTheScriptsStillCarryTheirOwnGuard:
    """
    Before comparing documents to the constants, that the constants exist.

    Deleting `EXPECTED_CHECKS` would make every check below vacuous: there
    would be nothing for the documents to disagree with, and this file
    would pass over a live run that had stopped counting itself.
    """

    def test_the_http_run_states_how_many_checks_it_expects(self):
        assert literal_in(SMOKE, "EXPECTED_CHECKS") > 0

    def test_the_browser_run_states_how_many_checks_it_expects(self):
        assert literal_in(BROWSER, "expected") > 0


class TestNoDocumentStatesASizeNobodyRuns:

    @pytest.mark.parametrize("document", DOCUMENTS)
    def test_every_count_it_prints_is_one_the_runs_carry(self, document, sizes):
        """
        The drift this file exists for.

        Not "the document says 123" -- that would pin the wording. Any
        count stated has to be a size some run actually claims, which is
        what makes a stale 118 red and a rename harmless.

        Args:
            document: Repository-relative path, one test per file.
            sizes: The published sizes.
        """
        stale = [count for count in counts_in(document) if count not in sizes]

        assert not stale, (
            f"{document} states {stale}, and the runs carry {sorted(sizes)}"
        )

    @pytest.mark.parametrize("document", DOCUMENTS)
    def test_it_still_states_them_at_all(self, document, sizes):
        """
        The other way to pass: a document that mentions no number cannot
        state a wrong one. Both runs are named in all five of these, and a
        reader deciding whether to run them wants to know the size.

        Args:
            document: Repository-relative path, one test per file.
            sizes: The published sizes.
        """
        assert set(counts_in(document)) == sizes, (
            f"{document} names {sorted(set(counts_in(document)))}, "
            f"expected both of {sorted(sizes)}"
        )


def measurement_clauses():
    """
    The clauses in ``docs/testing.md`` that state the VERIFY_PATH result.

    Every "gives ..." in the document is looked at and only the ones
    carrying a fraction are kept. Taking the first "gives" instead was
    enough until a sentence about a check "gives its context a locale" was
    written above it -- after which this file failed with "stated over
    []", naming neither the real sentence nor the new one. An anchor made
    of an ordinary English word cannot be reserved; a fraction is what the
    measurement actually looks like.

    Returns:
        List of clauses, each holding at least one fraction.

    Raises:
        AssertionError: If the measurement is stated nowhere.
    """
    prose = " ".join(
        (ROOT / "docs/testing.md").read_text(encoding="utf-8").split()
    )
    clauses = [
        found.group(1)
        for found in re.finditer(r"gives ([^.]+)\.", prose)
        if FRACTION.search(found.group(1))
    ]

    assert clauses, "the VERIFY_PATH measurement is no longer stated"
    return clauses


class TestTheMeasurementsAgainstTheirDenominator:
    """
    ``docs/testing.md`` prints what a deliberate breakage reddened:
    "81/123, the browser run 10/25". The numerator came from a run nobody
    can repeat from here; the denominator is a published size and has to
    keep up with it.
    """

    def test_every_fraction_is_over_a_size_a_run_carries(self, sizes):
        denominators = {
            int(whole)
            for clause in measurement_clauses()
            for _part, whole in FRACTION.findall(clause)
        }

        assert denominators == sizes, (
            f"the measurement is stated over {sorted(denominators)}, "
            f"and the runs carry {sorted(sizes)}"
        )

    def test_each_numerator_is_smaller_than_its_denominator(self, sizes):
        """
        A count of checks that noticed cannot exceed the checks that ran.
        Not a strong statement -- it is the one thing about the numerator
        that can be checked without running the breakage again.
        """
        for clause in measurement_clauses():
            for part, whole in FRACTION.findall(clause):
                assert 0 < int(part) <= int(whole), f"{part}/{whole} is not a share"
