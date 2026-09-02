"""A translated document is a second source, and it drifts on its own.

Two documents exist in both languages, and prose is not what goes wrong in
them: a sentence rewritten in Russian says what its author meant. What goes
wrong is everything that is not prose -- a setting renamed on one side, an
endpoint added to one table, a screenshot that reached one file, a number
updated where it was noticed.

Both were found that way. `docs/getting-started.ru.md` had no
`media/dashboard.png` and no paragraph about it, so a Russian reader was
never shown the running product the English reader is shown two screens in;
and the example answer to `POST /api/v1/shorten` was four fields short in
*both* files, which is how the same edit misses both twins at once.

What is compared is the machine-readable half -- setting names, commands,
routes, permissions, image sources, and numbers of two digits or more --
as sets. Not counts: one language will mention a name once more than the
other for reasons of grammar, and a check on counts is one people learn to
work around rather than to satisfy.
"""

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]

PAIRS = [
    ("README.md", "README.ru.md"),
    ("docs/getting-started.md", "docs/getting-started.ru.md"),
]

KINDS = {
    "setting": r'`([A-Z][A-Z0-9_]{2,})`',
    "command": r'`((?:uv run )?flask [a-z][\w -]*)`',
    "route": r'`(/[\w/{}.\-]*)`',
    "permission": r'`([a-z_]+:[a-z_]+)`',
    "image": r'<img[^>]+src="([^"]+)"',
    # Two digits or more: a lone digit is "one of them" far more often than
    # it is a figure, in either language.
    "number": r'(?<![\w.\-/])(\d{2,})(?![\w.%])',
}


def tokens(rel: str, kind: str) -> set:
    body = (ROOT / rel).read_text(encoding="utf-8")
    found = re.findall(KINDS[kind], body)
    if kind == "command":
        return {" ".join(x.split()) for x in found}
    return set(found)


CASES = [(en, ru, kind) for en, ru in PAIRS for kind in KINDS]


@pytest.mark.parametrize(
    "en, ru, kind", CASES, ids=[f"{Path(e).name}:{k}" for e, _, k in CASES]
)
def test_both_languages_carry_the_same(en, ru, kind):
    in_english, in_russian = tokens(en, kind), tokens(ru, kind)

    only_english = in_english - in_russian
    only_russian = in_russian - in_english

    assert not only_english and not only_russian, (
        f"{kind} differs between the two versions:\n"
        f"  only in {en}: {sorted(only_english)}\n"
        f"  only in {ru}: {sorted(only_russian)}"
    )


EXPECTED = {
    "README.md": {
        "setting": 5, "route": 32, "permission": 14, "image": 2, "number": 14,
    },
    "docs/getting-started.md": {
        "setting": 22, "command": 10, "route": 4, "permission": 8,
        "image": 2, "number": 25,
    },
}
"""How much each pattern finds today, in the English of each pair.

Two sets that are both empty agree with each other, so a pattern that
quietly stopped matching would turn every comparison above into a
comparison of nothing. A floor is not enough either: a pattern narrowed
from thirty-one routes to two would still be "not empty".

`README.md` yields no commands on purpose -- the commands there live in
fenced blocks rather than in backticks -- so the kind is absent from its
row rather than written as zero.

These numbers move when a document gains a setting or a route, which is an
ordinary edit; update them with it. What they are here for is the edit
nobody meant to make.
"""


@pytest.mark.parametrize("rel", sorted(EXPECTED))
def test_the_patterns_still_find_what_they_found(rel):
    counted = {kind: len(tokens(rel, kind)) for kind in EXPECTED[rel]}

    assert counted == EXPECTED[rel], (
        f"what {rel} yields has changed: {counted} against {EXPECTED[rel]}. "
        f"If the document grew, update the expectation; if it did not, a "
        f"pattern above has stopped matching and the comparisons are empty"
    )


DESTRUCTIVE = "down -v"
"""The flag that removes the volumes, and with them the database."""

SAYS_WHAT_IS_LOST = {
    "en": re.compile(
        r"takes the data with it|destroy|delete|erase|wipe|lose|loses|lost",
        re.IGNORECASE,
    ),
    "ru": re.compile(
        # Both stems of "erase": `стирать` gives "стирает", `стереть`
        # gives "стерев" and "стёр" -- and the second is the one the
        # sentence actually uses. Written with only the first, this check
        # reddened on the corrected document, which is the right failure
        # to have had: a pattern that misses the word is a check that
        # would have passed the defect.
        r"стир|стер|стёр|сотр|удал|уничтож|потер|очист", re.IGNORECASE
    ),
}
"""Words that name a loss, per language.

Wide on purpose: the check is that the sentence says *something* is
destroyed, not that it says it in one blessed phrasing. Rewording the
sentence must not redden this; dropping the consequence must.
"""


def sentences_naming(rel: str, needle: str) -> list:
    """
    The lines of a document that mention something.

    Whole lines rather than parsed sentences, because both guides carry
    this advice inside a table row, where the consequence sits between two
    dashes and no sentence splitter would keep it with its command.

    Args:
        rel: Path of the document, relative to the repository root.
        needle: What the line must mention.

    Returns:
        The lines that mention it.
    """
    return [
        line for line in (ROOT / rel).read_text(encoding="utf-8").splitlines()
        if needle in line
    ]


class TestADestructiveCommandNamesWhatItDestroys:
    """
    A warning is the easiest thing to lose in translation.

    Prose is not what the checks above look at, and rightly -- a sentence
    rewritten in Russian says what its author meant. This one is the
    exception, because it is not really prose: `down -v` removes the
    volumes, and the sentence offering it as a remedy for a password
    mismatch is the only place a reader is told so.

    Measured before this: the English row said "it takes the data with
    it"; the Russian said "начать заново, вместе с данными" -- an
    appositive with no verb, which reads as easily as "start over, with
    the data still there". A reader following the Russian could run it on
    a stack holding real data believing the data survives.
    """

    @pytest.mark.parametrize("en, ru", PAIRS)
    def test_both_languages_name_the_loss(self, en, ru):
        for rel, language in ((en, "en"), (ru, "ru")):
            for line in sentences_naming(rel, DESTRUCTIVE):
                assert SAYS_WHAT_IS_LOST[language].search(line), (
                    f"{rel} offers `{DESTRUCTIVE}` without saying what it "
                    f"removes: {line.strip()[:160]}"
                )

    def test_the_guides_still_carry_the_advice(self):
        """
        The check above passes in silence over a document that stopped
        mentioning the command at all, which is how a check like this
        rots. Both guides have to still be saying it.
        """
        for rel in ("docs/getting-started.md", "docs/getting-started.ru.md"):
            assert sentences_naming(rel, DESTRUCTIVE), (
                f"{rel} no longer mentions `{DESTRUCTIVE}`; if that is "
                f"deliberate, this check has nothing left to hold"
            )
