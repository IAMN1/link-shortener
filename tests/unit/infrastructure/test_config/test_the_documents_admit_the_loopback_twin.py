"""
What the settings documents say about the second spelling of this machine.

The CSRF layer derives the other spelling of a loopback ``BASE_URL`` --
``localhost`` from ``127.0.0.1`` and back -- at whatever port ``BASE_URL``
names, so a signed-in form is accepted from either. That is held over the
running application in
``tests/integration/web/middleware/test_the_own_domain_needs_no_cors_entry.py``.

Nothing held the documents. The change landed, the behaviour is right,
and four passages went on telling the reader the opposite:

    .env.example / .env.docker.example
        ... and "CSRF token missing or invalid" on every form the
        moment they sign in -- measured on a live run.
    docs/configuration.md
        ... "CSRF token missing or invalid" on every form the moment you
        sign in. Measured on the Docker stack.
        The Docker case above is the third row ... The fix is either
        spelling -- name it here, or make it the one `DOMAIN` says.

Measured against the running service afterwards, on a stack published at
5101 whose ``CORS_ORIGINS`` named only port 5000: ``Origin:
http://localhost:5101`` and ``Origin: http://127.0.0.1:5101`` both
answered ``201`` on a cookie-authenticated ``POST``, and
``http://evil.example.com`` answered ``403``.

Two things are checked, and they fail differently. The ban list catches a
revert to the exact sentences that were wrong. The requirement catches a
document that describes the failure and never says it was fixed -- which
is what a reader meets, and what no ban list would notice in a rewrite.

The premise is taken from the code, not from the documents: while
``LOOPBACK_TWINS`` is empty the sentences would be true again, and this
file says so rather than failing at a reader who removed the feature on
purpose.
"""

from pathlib import Path

import pytest

from link_shortener.web.middleware.csrf import LOOPBACK_TWINS


ROOT = Path(__file__).resolve().parents[4]

DOCUMENTS = {
    ".env.example": ROOT / ".env.example",
    ".env.docker.example": ROOT / ".env.docker.example",
    "docs/configuration.md": ROOT / "docs/configuration.md",
}
"""The settings documents that describe the CSRF origin comparison."""

RETIRED_SENTENCES = (
    'on every form the\n# moment they sign in -- measured on a live run.',
    'token missing or invalid" on every form the moment you sign in. Measured\n> on the Docker stack.',
    "The fix\n> is either spelling — name it here, or make it the one `DOMAIN` says.",
)
"""Quoted from the documents as they stood while the twin already worked.

A pattern for the true statement would not do: there are many right ways
to describe the twin and only these wrong ones were written.
"""

TWIN_IS_ADMITTED = "both spellings"
"""The phrase each document uses to say the twin is admitted.

Short and deliberately plain: what is being checked is that the
correction is somewhere in the file a reader has open, not that it is
phrased any particular way beyond this.
"""


@pytest.fixture(scope="module")
def texts() -> dict:
    """Each document, read once."""
    return {name: path.read_text(encoding="utf-8") for name, path in DOCUMENTS.items()}


class TestThePremise:

    def test_the_twin_is_still_derived(self):
        """
        With no twin the retired sentences become true again.

        Told here rather than left as four confusing failures in the
        checks below.
        """
        assert LOOPBACK_TWINS, (
            "LOOPBACK_TWINS is empty: the second spelling of the loopback "
            "is no longer admitted, and the sentences this file bans "
            "describe the service again"
        )

    def test_every_document_was_found(self, texts):
        """A path that stopped resolving would pass everything below."""
        assert len(texts) == len(DOCUMENTS)
        for name, text in texts.items():
            assert text.strip(), name


class TestNoDocumentStillSaysTheFormFails:

    @pytest.mark.parametrize("sentence", RETIRED_SENTENCES)
    def test_the_sentence_is_gone_from_every_document(self, texts, sentence):
        carrying = [name for name, text in texts.items() if sentence in text]

        assert not carrying, (
            f"{carrying} still carry a sentence that says a signed-in form "
            f"is refused from the other spelling of the loopback, which the "
            f"CSRF layer has admitted since LOOPBACK_TWINS was added"
        )


class TestEveryDocumentSaysTheTwinIsAdmitted:

    @pytest.mark.parametrize("name", sorted(DOCUMENTS))
    def test_the_document_tells_the_reader(self, texts, name):
        """
        Describing the old failure without the correction is the defect.

        Each of these files explains the origin comparison to somebody
        about to set `CORS_ORIGINS`. A file that describes the comparison
        and never mentions the twin sends them to name an origin the
        service admits on its own.
        """
        assert TWIN_IS_ADMITTED in texts[name], (
            f"{name} describes the CSRF origin comparison without saying "
            f"that both spellings of the loopback are admitted"
        )
