"""Every link between these documents, and every anchor one points at.

There are 154 of them across sixteen files and nothing read any. A broken
one is invisible from inside the repository -- the markdown renders, the
text reads the same, and the failure appears only when somebody clicks it
on GitHub and lands on a 404 or at the top of the right page instead of the
section they were sent to.

Anchors are the half that rots quietly. A link keeps working while the file
exists, so `[Configuration](configuration.md#rate-limits)` survives every
edit to that document except the one that renames its heading -- and
renaming a heading is an ordinary, invisible edit.

The slug rule is GitHub's: lower-case, punctuation dropped, spaces to
hyphens, a numeric suffix for a repeated heading. It is applied to the
heading text with inline formatting stripped first, since `## `LOG_DIR``
renders as `log_dir` and not as `-log_dir-`.

External links are not checked. They leave this machine, they fail for
reasons that have nothing to do with this repository, and a suite that goes
red because somebody else's site is down is a suite people learn to ignore.
"""

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]

SKIP = {".venv", ".git", "htmlcov", "node_modules", "__pycache__",
        ".mypy_cache", ".pytest_cache", "test-results", "site-packages"}

LINK = re.compile(r'\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)')
HEADING = re.compile(r'^(#{1,6})\s+(.*?)\s*#*\s*$', re.M)
EXPLICIT = re.compile(r'<a\s+(?:name|id)="([^"]+)"')
FENCE = re.compile(r'```.*?```', re.S)


def documents():
    """Every markdown file this repository owns."""
    return sorted(
        p for p in ROOT.rglob("*.md")
        if not SKIP & set(p.parts)
    )


def slug(text: str) -> str:
    """A heading, as GitHub turns it into an anchor."""
    text = re.sub(r'`([^`]*)`', r'\1', text)
    text = re.sub(r'\*\*([^*]*)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]*)\*', r'\1', text)
    text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)
    text = text.strip().lower()
    text = re.sub(r'[^\w\s-]', '', text, flags=re.U)
    return text.replace(' ', '-')


def anchors(path: Path) -> set:
    """Every fragment that resolves inside one file."""
    body = path.read_text(encoding="utf-8")
    found, seen = set(), {}
    for _, title in HEADING.findall(body):
        base = slug(title)
        n = seen.get(base, 0)
        seen[base] = n + 1
        found.add(base if n == 0 else f"{base}-{n}")
    return found | set(EXPLICIT.findall(body))


def internal_links():
    """Every internal link in the tree: (source, text, target)."""
    out = []
    for doc in documents():
        body = doc.read_text(encoding="utf-8")
        # Blank the fenced blocks, keeping the line count, so an example
        # link inside one is not read as a link this repository owns.
        outside = FENCE.sub(lambda m: "\n" * m.group(0).count("\n"), body)
        for text, target in LINK.findall(outside):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            line = outside[:outside.index(f"]({target})")].count("\n") + 1
            out.append((doc, line, text, target))
    return out


LINKS = internal_links()

CROSS_FILE = [case for case in LINKS if not case[3].startswith("#")]
"""Links that name a file. A same-file anchor names none."""

WITH_ANCHOR = [case for case in LINKS if "#" in case[3]]
"""Links that name a fragment, whether or not they also name a file."""

# Split into two lists rather than one list with a skip in each check.
# `--error-for-skips` is what CI runs the suite under, so a skip here is a
# failed build -- and it would be a failure that says nothing, since the
# skip is not a case that could not be decided but a case that belongs to
# the other check.


def _id(case):
    doc, line, _, target = case
    return f"{doc.relative_to(ROOT)}:{line}->{target}"


class TestEveryInternalLinkLandsSomewhere:

    def test_there_are_links_to_check(self):
        """
        A discovery bug that found nothing would make every check below
        pass by vacancy, which is the failure this suite guards against
        everywhere else.
        """
        assert len(LINKS) > 100, f"only {len(LINKS)} internal links found"
        assert CROSS_FILE, "no link names a file"
        assert WITH_ANCHOR, "no link names an anchor"

    @pytest.mark.parametrize("case", CROSS_FILE, ids=_id)
    def test_the_file_it_points_at_exists(self, case):
        doc, line, text, target = case

        path = (doc.parent / target.partition("#")[0]).resolve()

        assert path.exists(), (
            f"{doc.relative_to(ROOT)}:{line} points at {target}, "
            f"which is not in the tree"
        )

    @pytest.mark.parametrize("case", WITH_ANCHOR, ids=_id)
    def test_the_anchor_it_points_at_exists(self, case):
        doc, line, text, target = case
        file_part, _, fragment = target.partition("#")

        path = doc if not file_part else (doc.parent / file_part).resolve()

        assert path.exists(), (
            f"{doc.relative_to(ROOT)}:{line} points at {target}, and "
            f"{file_part} is not in the tree"
        )

        available = {a.lower() for a in anchors(path)}

        assert fragment.lower() in available, (
            f"{doc.relative_to(ROOT)}:{line} points at #{fragment} in "
            f"{path.name}, which has no such heading"
        )
