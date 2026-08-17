"""
The catalogues, and the text that is supposed to be in them.

Four faults live here, and none of them raises anything at runtime. A page
with a string nobody marked renders perfectly, in English, on a Russian
page. A catalogue with an empty entry renders the English source, because
that is exactly what gettext falls back to. A catalogue translated but never
compiled renders the English source too -- ``gettext`` reads ``.mo`` and
never looks at the ``.po`` beside it. And a template file that was never
re-extracted leaves a new string out of every catalogue at once.

All four look identical from outside: the page comes out in the wrong
language and nothing is logged. Only a test that reads the files can tell
them apart, which is why they are read here rather than exercised.
"""

import pathlib
import re
import subprocess
import sys
import tempfile

import pytest
from babel.messages.mofile import read_mo
from babel.messages.pofile import read_po

import link_shortener.web
from link_shortener.web.i18n import script_strings


WEB = pathlib.Path(link_shortener.web.__file__).parent
TRANSLATIONS = WEB / "translations"
TEMPLATES = WEB / "templates"
ROOT = WEB.parents[2]
"""The project root -- ``src/link_shortener/web`` is three levels down."""

LANGUAGES = ("ru", "zh")
"""Languages with a catalogue.

English has none and needs none: an untranslated ``gettext`` call answers
its own msgid, and the msgids are the English text.
"""


def catalogue(language, suffix):
    """
    Read one compiled or source catalogue.

    Args:
        language: Language tag, e.g. ``ru``.
        suffix: ``po`` or ``mo``.

    Returns:
        The parsed catalogue.
    """
    path = TRANSLATIONS / language / "LC_MESSAGES" / f"messages.{suffix}"
    assert path.is_file(), f"{path} is missing"

    if suffix == "po":
        with path.open(encoding="utf-8") as handle:
            return read_po(handle, locale=language)

    with path.open("rb") as handle:
        return read_mo(handle)


def translated(message):
    """
    Say whether a message carries a translation.

    Args:
        message: A catalogue entry.

    Returns:
        ``True`` when every plural form is filled in.
    """
    if isinstance(message.string, (list, tuple)):
        return all(form for form in message.string)
    return bool(message.string)


class TestEveryStringIsTranslated:

    @pytest.mark.parametrize("language", LANGUAGES)
    def test_no_entry_is_left_empty(self, language):
        """
        An empty entry is not a visible gap: gettext answers the msgid,
        which is the English text, so the page comes out looking finished
        and reads half in one language.
        """
        empty = [
            message.id for message in catalogue(language, "po")
            if message.id and not translated(message)
        ]

        assert empty == [], f"{language} has untranslated entries: {empty}"

    @pytest.mark.parametrize("language", LANGUAGES)
    def test_nothing_is_marked_fuzzy(self, language):
        """
        ``pybabel update`` marks a guessed translation fuzzy, and gettext
        **ignores** a fuzzy entry -- it answers the English source instead.
        A catalogue that looks fully translated in an editor can therefore
        render entirely in English.
        """
        fuzzy = [
            message.id for message in catalogue(language, "po")
            if message.id and "fuzzy" in message.flags
        ]

        assert fuzzy == [], f"{language} has fuzzy entries gettext will skip: {fuzzy}"

    @pytest.mark.parametrize("language", LANGUAGES)
    def test_the_russian_plurals_have_all_three_forms(self, language):
        """
        Russian needs three (1 ссылка / 2 ссылки / 5 ссылок) and Chinese
        one. A catalogue carrying fewer than its language declares makes
        ``ngettext`` fall through to the English source for the missing
        form -- and only for some numbers, which is the hardest kind of
        bug to notice.
        """
        source = catalogue(language, "po")
        for message in source:
            if not message.id or not isinstance(message.id, (list, tuple)):
                continue

            assert len(message.string) == source.num_plurals, (
                f"{language}: {message.id[0]!r} has {len(message.string)} forms, "
                f"the language declares {source.num_plurals}"
            )


class TestTheCompiledCatalogueIsInStep:
    """
    ``gettext`` reads ``.mo`` and never looks at the ``.po`` beside it.

    So a translation that was written and not compiled is a translation
    that does not exist, and the page renders in English with a fully
    translated ``.po`` sitting in the repository.
    """

    @pytest.mark.parametrize("language", LANGUAGES)
    def test_every_translation_reached_the_compiled_one_unchanged(self, language):
        """
        The **text** is compared, not merely the presence of the entry.

        Measured: with presence alone, editing a translation in the ``.po``
        and not recompiling passed -- which is the ordinary shape of this
        mistake, far more ordinary than adding a whole new string. The
        wording on the page then stays whatever it was at the last
        compile, and the repository shows the new wording.
        """
        # Built by walking the compiled catalogue rather than by asking it
        # `in`: a message with a context is keyed by the pair, and the
        # reader hands the context back as **bytes** while the source
        # catalogue holds it as text. Asked directly, the pair never
        # matches and every contextual message reads as uncompiled --
        # measured, and it is why the keys are normalised here.
        def key(message):
            context = message.context
            if isinstance(context, bytes):
                context = context.decode()
            text = message.id[0] if isinstance(message.id, (list, tuple)) else message.id
            return context, text

        def forms(message):
            return tuple(message.string) if isinstance(message.string, (list, tuple)) \
                else (message.string,)

        compiled = {
            key(message): forms(message)
            for message in catalogue(language, "mo") if message.id
        }

        stale = []
        for message in catalogue(language, "po"):
            if not message.id or not translated(message):
                continue
            if compiled.get(key(message)) != forms(message):
                stale.append(key(message)[1])

        assert stale == [], (
            f"{language}: the .po and the .mo disagree -- re-run "
            f"`pybabel compile`: {stale}"
        )


class TestTheTemplateOnDiskIsCurrent:

    def test_extracting_again_finds_nothing_new(self):
        """
        The one fault the checks above cannot see: a string marked in a
        template and never extracted is in no catalogue at all, so there is
        no empty entry to find. Extraction is run again here and compared
        against what is on disk.

        Only the set of messages is compared, not the file: the header
        carries a generation date, and line numbers move whenever anything
        above them does.
        """
        with tempfile.TemporaryDirectory() as workspace:
            fresh = pathlib.Path(workspace) / "messages.pot"
            # Through the interpreter running this test, not the `pybabel`
            # on PATH: the suite is driven by the virtual environment's
            # own interpreter, whose `bin` is not on PATH, and the bare
            # name is simply not found there.
            done = subprocess.run(
                [sys.executable, "-m", "babel.messages.frontend",
                 "extract", "-F", "babel.cfg", "-o", str(fresh),
                 "--project=link-shortener", "--version=0.1.0", "."],
                cwd=ROOT, capture_output=True, text=True,
            )
            assert done.returncode == 0, done.stderr

            with fresh.open(encoding="utf-8") as handle:
                found = read_po(handle)

        with (TRANSLATIONS / "messages.pot").open(encoding="utf-8") as handle:
            shipped = read_po(handle)

        def keys(cat):
            return {
                (m.context, m.id[0] if isinstance(m.id, (list, tuple)) else m.id)
                for m in cat if m.id
            }

        new = keys(found) - keys(shipped)
        gone = keys(shipped) - keys(found)

        assert not new, f"marked but never extracted -- re-run `pybabel extract`: {new}"
        assert not gone, f"extracted but no longer in any template: {gone}"


# ==========================================================================
# Text that is deliberately not translated
# ==========================================================================
NOT_PROSE = {
    # Addresses and verbs of the API. Translating a path would translate
    # the request itself.
    "GET /api/v1/links/{code}",
    "POST /api/v1/shorten",
    "api/v1/shorten",
    "POST",
    "openapi.json",
    "API",
    # The example call on the landing page, printed as a shell would take
    # it. Every word in it is typed by a machine, not read by a person.
    "curl",
    "'Content-Type: application/json'",
    '\'{"url": "https://example.com/…"}\'',
    # Names: the product, the author, the services it talks to.
    "Linkr",
    "linkr",
    "— Linkr",
    "2026 Linkr",
    "GitHub",
    "Redis",
    # The key, as it is printed on a keyboard the world over.
    "Enter",
}
"""Text nodes the scan below is allowed to find.

Each one is here for a reason, and the reason is the same in every case:
translating it would change something other than a sentence. A new entry
needs a new reason, which is the whole point of the list being written out
rather than the scan being loosened.
"""

TRANS_BLOCK = re.compile(r"\{%-?\s*trans\b.*?\{%-?\s*endtrans\s*-?%\}", re.S)
SET_BLOCK = re.compile(r"\{%-?\s*set\s+\w+\s*-?%\}.*?\{%-?\s*endset\s*-?%\}", re.S)
MAIN_CLASS = re.compile(r"\{%\s*block\s+main_class\s*%\}.*?\{%\s*endblock\s*%\}", re.S)
JINJA = re.compile(r"\{%.*?%\}|\{\{.*?\}\}", re.S)
JINJA_COMMENT = re.compile(r"\{#.*?#\}", re.S)
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
SCRIPT_OR_STYLE = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
TAG = re.compile(r"<[^>]*>", re.S)
ENTITY = re.compile(r"&[a-z]+;|&#\d+;")


def readable_text(template):
    """
    Everything in a template a person would read off the screen.

    Removed first, in this order and for these reasons: HTML comments and
    Jinja comments are not on the page; ``<script>`` and ``<style>`` are not
    prose; a ``{% trans %}`` block is text that **is** translated, and its
    body would otherwise be read as raw; a ``{% set %}...{% endset %}``
    block holds the markup such a translation substitutes into.

    Args:
        template: Path to a template.

    Returns:
        Iterator over the text nodes that carry Latin letters.
    """
    text = template.read_text(encoding="utf-8")
    # Comments go before anything else looks at the file, because a comment
    # is not on the page at all and its *contents* are not markup. This
    # order used to be the other way round and the file said otherwise:
    # `layout/base.html` explains the page scripts in a Jinja comment that
    # spells out `<script src>`, so the moment a real `<script>` was added
    # below it, the scan matched that opening tag against the new block's
    # closing one, cut out everything between them and reported the
    # remainder of the comment as untranslated prose on the page.
    text = HTML_COMMENT.sub(" ", text)
    text = JINJA_COMMENT.sub(" ", text)
    text = SCRIPT_OR_STYLE.sub(" ", text)
    text = TRANS_BLOCK.sub(" ", text)
    text = SET_BLOCK.sub(" ", text)
    text = MAIN_CLASS.sub(" ", text)
    # A marker rather than a space: `{{ x }}y` and `{{ x }} y` are different
    # sentences, and collapsing both to `y` would hide a missing space.
    text = JINJA.sub("\x00", text)

    for piece in TAG.sub("\n", text).split("\n"):
        piece = ENTITY.sub(" ", piece.replace("\x00", " ")).strip()
        if re.search(r"[A-Za-z]{2}", piece):
            yield piece


class TestNoPageCarriesUnmarkedText:
    """
    The fault the catalogues cannot see.

    A sentence written straight into a template is in no catalogue, so
    there is no empty entry, no fuzzy entry and no missing compilation --
    the page simply comes out with one English line in the middle of a
    Russian screen. Nothing fails, and the only way to find it is to look.
    """

    def test_every_readable_string_is_marked_for_translation(self):
        unmarked = {}
        for template in sorted(TEMPLATES.rglob("*.html")):
            for piece in readable_text(template):
                if piece in NOT_PROSE:
                    continue
                unmarked.setdefault(piece, []).append(template.name)

        assert unmarked == {}, (
            "text on a page that no catalogue can reach -- wrap it in "
            f"`_()` or `{{% trans %}}`: {unmarked}"
        )

    def test_the_allow_list_has_no_dead_entries(self):
        """
        An exception that no longer matches anything is an exception
        nobody will question, and the next reader will take it for a rule.
        """
        seen = set()
        for template in TEMPLATES.rglob("*.html"):
            seen.update(readable_text(template))

        dead = NOT_PROSE - seen

        assert dead == set(), f"NOT_PROSE names text no template carries: {dead}"


SCRIPTS = WEB / "static" / "js"
"""The page scripts. ``static/vendor`` is somebody else's code and is not
scanned: Turbo carries English of its own, none of it ever reaches a page
this project draws, and rewriting a vendored file is how a vendored file
stops being the thing whose checksum is pinned."""

JS_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
JS_LINE_COMMENT = re.compile(r"^\s*//.*$", re.M)
JS_LITERAL = re.compile(r"'((?:[^'\\\n]|\\.)*)'|\"((?:[^\"\\\n]|\\.)*)\"")
JS_TEXT_IN_HTML = re.compile(r">([^<>'\"]*[A-Za-z]{2}[^<>'\"]*)<")
JS_CODE_ONLY = re.compile(r"^[a-z0-9 ._#\[\]()=:;/&-]*$")
"""A literal made of nothing but the alphabet of selectors, classes, paths
and cookie attributes. Prose has a capital or a comma somewhere in it; a
class name does not."""

T_CALL = re.compile(r"\bt\(\s*'([a-z_]+)'")
"""A script asking for one sentence.

The key has to be a literal directly inside the call. `t(ok ? 'a' : 'b')`
would be legal JavaScript and invisible here, so the scripts do not write
it that way -- the comment in `pages/health.js` says why.
"""

NOT_PROSE_JS = {
    # The methods, as HTTP spells them.
    "GET",
    "HEAD",
    "POST",
    "PUT",
    "DELETE",
    "OPTIONS",
    "TRACE",
    # Header names, which are protocol and not language.
    "Content-Type",
    "X-CSRF-Token",
    "X-Deletion-Token",
    # The keys, as they are printed on a keyboard the world over -- and as
    # `KeyboardEvent.key` spells them, which makes them protocol rather
    # than language: a translated "Enter" would compare equal to nothing.
    "Escape",
    "Enter",
    # Selectors carrying a quoted attribute, which is why they survive the
    # code-only filter above.
    'button[type="submit"]',
    'input[name="roles"]:checked',
    'input[name="permissions"]:checked',
    # Halves of an attribute a script builds around a value.
    ' data-code="',
    ' data-token="',
    # How long a preference is kept and where it is sent.
    ";path=/;max-age=31536000;samesite=Lax",
}
"""Strings in the scripts that are not sentences.

The same rule as ``NOT_PROSE``: each entry is here because translating it
would change something other than a sentence, and a new entry needs a new
reason.
"""


def readable_script_text(script):
    """
    Everything in a page script that a person could end up reading.

    Two shapes, because the scripts write text in two ways: as a string of
    its own -- ``confirm('Delete this?')`` -- and as a text node inside
    markup being concatenated -- ``'<span>Clicks</span>'``. The second one
    is the one a search for quoted sentences misses, and sixteen of the
    strings this file exists to catch were of that kind.

    Args:
        script: Path to a ``.js`` file.

    Returns:
        Iterator over the pieces that could be prose.
    """
    text = script.read_text(encoding="utf-8")
    text = JS_BLOCK_COMMENT.sub(" ", text)
    text = JS_LINE_COMMENT.sub("", text)

    for match in JS_LITERAL.finditer(text):
        value = match.group(1) if match.group(1) is not None else match.group(2)
        # A literal holding markup is examined by the second pass below;
        # taken whole it is a wall of tags and classes.
        if "<" in value or ">" in value:
            # The second pass, applied to this literal rather than to the
            # file. Over the whole file it also matched between two
            # *operators* -- `index >= LIMIT` on one line and
            # `rows.length <` on the next put a `>` before a `<` with
            # ordinary code in between, and the code was reported as a
            # sentence a translator must handle. Markup only ever lives
            # inside a literal, so narrowing the pass to literals loses no
            # text node and drops that whole class of false report.
            for node in JS_TEXT_IN_HTML.finditer(value):
                piece = node.group(1).strip()
                # `+` means the fragment was cut here by a concatenation,
                # so this is not a text node -- it is the seam between two
                # of them.
                if piece and "+" not in piece and re.search(r"[A-Za-z]{2}", piece):
                    yield piece
            continue
        if not re.search(r"[A-Za-z]{2}", value):
            continue
        if JS_CODE_ONLY.match(value):
            continue
        yield value


class TestNoScriptCarriesUnmarkedText:
    """
    The sixth way to answer in the wrong language, and the quietest.

    A page script runs in the browser, where the catalogues are not. A
    sentence typed into a ``.js`` file is therefore in whatever language it
    was typed in, on every page, in every language -- and nothing but a
    browser ever executes these files, so the whole suite stays green while
    a Russian page fills itself with English.

    The strings live in ``web/i18n.py:script_strings`` and reach the
    browser through ``layout/base.html``; a script asks for one by key.
    """

    def test_every_readable_string_is_marked_for_translation(self):
        unmarked = {}
        for script in sorted(SCRIPTS.rglob("*.js")):
            for piece in readable_script_text(script):
                if piece in NOT_PROSE_JS:
                    continue
                unmarked.setdefault(piece, []).append(script.name)

        assert unmarked == {}, (
            "text a script writes onto the page that no catalogue can "
            f"reach -- move it into `script_strings` and ask for it with "
            f"`t('key')`: {unmarked}"
        )

    def test_the_allow_list_has_no_dead_entries(self):
        """
        An exception that no longer matches anything is an exception
        nobody will question, and the next reader will take it for a rule.
        """
        seen = set()
        for script in SCRIPTS.rglob("*.js"):
            seen.update(readable_script_text(script))

        dead = NOT_PROSE_JS - seen

        assert dead == set(), f"NOT_PROSE_JS names text no script carries: {dead}"


class TestTheScriptsAndTheCatalogueAgree:
    """
    The two halves of the client-side catalogue, checked against each
    other.

    ``t()`` answers an unknown key with the key itself, so a rename on
    either side puts ``no_links_yet`` on the page where a sentence belongs.
    It is not an error, nothing is logged, and the page otherwise works.
    """

    def keys_scripts_ask_for(self):
        asked = {}
        for script in SCRIPTS.rglob("*.js"):
            for key in T_CALL.findall(script.read_text(encoding="utf-8")):
                asked.setdefault(key, []).append(script.name)
        return asked

    def test_every_key_a_script_asks_for_is_offered(self, app):
        # A request context, because the strings are translated for the
        # language of a request; `/` is enough, nothing here reads the path.
        with app.test_request_context("/"):
            offered = set(script_strings())

        asked = self.keys_scripts_ask_for()
        missing = {key: files for key, files in asked.items() if key not in offered}

        assert missing == {}, (
            "a script asks for a key `script_strings` does not offer, and "
            f"`t` will print the key on the page: {missing}"
        )

    def test_no_key_is_offered_that_no_script_asks_for(self, app):
        with app.test_request_context("/"):
            offered = set(script_strings())

        unused = offered - set(self.keys_scripts_ask_for())

        assert unused == set(), (
            "`script_strings` carries a sentence to every page that no "
            f"script ever asks for: {unused}"
        )

    def test_every_offered_string_reached_the_catalogues(self, app):
        """
        Extraction actually found these.

        The strings are marked with ``gettext`` like any other, and an
        unextracted ``gettext`` call is the fifth fault this file is about:
        it raises nothing and answers its own msgid, which is English. With
        no request naming a language, ``select_language`` answers the
        default and every call returns its msgid -- so what is collected
        here is exactly the set of English sentences the scripts can show.
        """
        with app.test_request_context("/"):
            english = set(script_strings().values())

        for language in LANGUAGES:
            known = {message.id for message in catalogue(language, "po") if message.id}
            missing = sorted(english - known)

            assert missing == [], (
                f"{language}: sentences the scripts show that no catalogue "
                f"has an entry for -- re-run `pybabel extract`: {missing}"
            )
