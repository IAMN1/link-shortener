"""
The Russian guide names the parts of a page a Russian reader will see.

The interface is translated -- ``Accept-Language: ru`` returns
``<html lang="ru">`` with «Найти по коду» and «Одна ссылка» on it -- and
the Russian guide told the reader to look for **Look up a code**, **One
link**, **My Links**, **My Stats**, **Create Link** and **Service Stats**.
Not one of those captions is on the page they are sent to. Measured on a
running service before this was written.

It read as an oversight in a translation, and it is not: the English
guide is right to use the English captions, and the Russian one has to
use the Russian ones for exactly the same reason -- a caption is
something the reader hunts for with their eyes.

The Russian is taken from the catalogue rather than written here again.
Two copies of a translation are two things that can part, and the
catalogue is the one the page is rendered from -- so a caption retranslated
there and not here fails this rather than shipping a guide that names a
caption nobody has.

The English name is kept in the guide beside the Russian, in brackets: the
language is chosen by ``Accept-Language`` and a cookie, so the reader may
well be looking at the English page while holding the Russian guide.
"""

import pathlib

import pytest
from babel.messages.pofile import read_po


ROOT = pathlib.Path(__file__).resolve().parents[2]
GUIDE = ROOT / "docs/getting-started.ru.md"
CATALOGUE = (
    ROOT / "src/link_shortener/web/translations/ru/LC_MESSAGES/messages.po"
)

NAMED_IN_THE_GUIDE = (
    "Look up a code",
    "One link",
    "Many at once",
    "My Links",
    "My Stats",
    "Create Link",
    "Service Stats",
    "Users",
    "Roles",
    "Journals",
    "Overview",
    "Security",
)
"""The captions the Russian guide points a reader at.

Listed rather than discovered: what the guide names is an editorial
choice, and a caption dropped from the guide should make this list wrong
and visible instead of quietly leaving the check with nothing to do.
"""


@pytest.fixture(scope="module")
def russian() -> dict:
    """Every English caption and its Russian, from the catalogue."""
    with CATALOGUE.open("rb") as handle:
        catalog = read_po(handle)
    return {
        message.id: message.string
        for message in catalog
        if isinstance(message.id, str) and message.string
    }


@pytest.fixture(scope="module")
def guide() -> str:
    return GUIDE.read_text(encoding="utf-8")


class TestTheCatalogueHasTheseCaptions:

    @pytest.mark.parametrize("caption", NAMED_IN_THE_GUIDE)
    def test_it_is_translated(self, russian, caption):
        """
        A caption with no translation would let the check below pass.

        It would also mean the page shows the English word to a Russian
        reader, in which case the guide naming it in English is right and
        this file is the wrong place to notice.
        """
        assert russian.get(caption), caption


class TestTheGuideUsesThem:

    @pytest.mark.parametrize("caption", NAMED_IN_THE_GUIDE)
    def test_the_russian_caption_is_in_the_guide(self, russian, guide, caption):
        assert russian[caption] in guide, (
            f"the Russian guide names '{caption}' but never "
            f"'{russian[caption]}', which is what the page says"
        )
