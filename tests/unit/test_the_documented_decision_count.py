"""How many decisions are written up, as published against as written.

Three documents state the number, in words, in two languages. Nothing read
any of them, and the number moves whenever a decision is added -- which is
what `CONTRIBUTING.md` asks a contributor to do.

It had already drifted: `decisions.md` held 92 entries while all three
documents said ninety-one. The drift is invisible by construction. The
sentence stays grammatical, the link still resolves, and the only way to
notice is to count `### ` headings by hand.

Counted two ways and both are required to agree, because either alone can
be fooled: a `### ` heading that is not a decision would inflate the first,
and a `**Decided**` line pasted into prose would inflate the second. They
disagree only if one of those happened, and then the count is not to be
trusted anyway.
"""

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
DECISIONS = ROOT / "docs" / "decisions.md"

DOCUMENTS = ("README.md", "README.ru.md", "docs/README.md")
"""Every file that states how many there are.

Listed rather than discovered: a document that stops saying it should make
this list wrong and visible, not quietly drop out of a search.
"""

ONES = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "один": 1, "два": 2, "три": 3, "четыре": 4, "пять": 5, "шесть": 6,
    "семь": 7, "восемь": 8, "девять": 9, "десять": 10,
}
TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100,
    "двадцать": 20, "тридцать": 30, "сорок": 40, "пятьдесят": 50,
    "шестьдесят": 60, "семьдесят": 70, "восемьдесят": 80,
    "девяносто": 90, "сто": 100,
}

WORDED = re.compile(
    r"\b(" + "|".join(TENS) + r")[- ]?(" + "|".join(ONES) + r")?\b",
    re.IGNORECASE,
)
"""A number written out, in either language.

Both are spelled the same way -- a tens word, optionally a ones word after
it -- so one pattern reads `ninety-five` and `девяносто пять` alike.
"""

NEAR = re.compile(
    r"(write-ups?|разбор\w*)",
    re.IGNORECASE,
)
"""The noun the number counts. Anchored on it so a `ninety days` elsewhere
in the same file is not read as a count of decisions."""


def worded(text: str):
    """Read a written-out number, or return None."""
    match = WORDED.search(text)
    if not match:
        return None
    total = TENS[match.group(1).lower()]
    if match.group(2):
        total += ONES[match.group(2).lower()]
    return total


def counted():
    """The two counts of `decisions.md`, as a pair."""
    body = DECISIONS.read_text(encoding="utf-8")
    return (
        len(re.findall(r"^### ", body, re.M)),
        len(re.findall(r"\*\*Decided\*\*", body)),
    )


def stated(rel: str):
    """Every worded count of decisions in one document, with its line."""
    found = []
    for number, line in enumerate(
        (ROOT / rel).read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not NEAR.search(line):
            continue
        value = worded(line)
        if value is not None:
            found.append((number, value, line.strip()))
    return found


class TestTheFileAgreesWithItself:

    def test_both_ways_of_counting_give_the_same_number(self):
        headings, decided = counted()

        assert headings == decided, (
            f"{headings} `### ` headings against {decided} `**Decided**` "
            f"lines: one of them is not a decision, and neither count can "
            f"be published until they agree"
        )


class TestEveryDocumentPublishesThatNumber:

    @pytest.mark.parametrize("rel", DOCUMENTS)
    def test_the_document_states_a_count_at_all(self, rel):
        """
        The list above is maintained by hand, so a document that stopped
        saying it has to fail here rather than pass by absence.
        """
        assert stated(rel), f"{rel} no longer states how many decisions there are"

    @pytest.mark.parametrize("rel", DOCUMENTS)
    def test_the_count_it_states_is_the_one_in_the_file(self, rel):
        headings, _ = counted()

        for line_number, value, text in stated(rel):
            assert value == headings, (
                f"{rel}:{line_number} says {value}, `decisions.md` holds "
                f"{headings}: {text}"
            )
