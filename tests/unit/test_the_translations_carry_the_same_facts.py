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
        "setting": 5, "route": 31, "permission": 14, "image": 2, "number": 12,
    },
    "docs/getting-started.md": {
        "setting": 21, "command": 9, "route": 3, "permission": 8,
        "image": 1, "number": 20,
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
