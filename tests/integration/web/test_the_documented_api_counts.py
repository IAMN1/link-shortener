"""The size of the published API, as `development.md` states it.

One sentence carries three numbers: how many paths the OpenAPI document
describes, how many operations, and how many of those are administrative.
All three move whenever an endpoint is added -- which is the one edit the
sentence exists to describe -- and nothing read them.

They had drifted by nine, ten and two: the page said "24 paths, 29
operations, of which 14 are administrative" while the document described
33, 39 and 16.

`test_api_docs.py` already holds the document against the real URL map, so
what is checked here is the other seam: the prose against the document.
Together they run from the route table to the sentence a reader trusts.
"""

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
PAGE = ROOT / "docs" / "development.md"

SENTENCE = re.compile(
    r"(\d+) paths, (\d+) operations, of\s+which (\d+) are administrative"
)

METHODS = {"get", "post", "put", "delete", "patch"}


@pytest.fixture
def document(client):
    return client.get("/api/openapi.json").get_json()


def measured(document):
    paths = document["paths"]
    operations = [
        (path, method)
        for path, item in paths.items()
        for method in item
        if method in METHODS
    ]
    administrative = [
        (path, method) for path, method in operations if "/admin" in path
    ]
    return len(paths), len(operations), len(administrative)


class TestTheSentenceStatesTheDocumentsOwnSize:

    def test_the_sentence_is_still_there(self):
        """
        The pattern is anchored on the words around the numbers, so a
        rewording removes the check rather than breaking it. That has to
        be a failure: a sentence nobody checks is how this drifted.
        """
        assert SENTENCE.search(PAGE.read_text(encoding="utf-8")), (
            "docs/development.md no longer states the size of the API "
            "document in the shape this test reads"
        )

    def test_the_three_numbers_are_the_documents(self, document):
        stated = SENTENCE.search(PAGE.read_text(encoding="utf-8"))
        paths, operations, administrative = (int(n) for n in stated.groups())

        assert (paths, operations, administrative) == measured(document), (
            f"docs/development.md says {paths} paths, {operations} "
            f"operations, {administrative} administrative; the document "
            f"describes {measured(document)}"
        )


class TestTheCountIsNotVacuous:
    """
    Every number above comes from the same document, so a document that
    came back empty would make the comparison a comparison of zeroes --
    and the page would have to say zero for it to pass, which is why this
    is separate rather than folded in.
    """

    def test_the_document_describes_something(self, document):
        paths, operations, administrative = measured(document)

        assert paths > 20
        assert operations >= paths
        assert 0 < administrative < operations
