"""
Tests that every page script is deferred, and why that is not a detail.

The page scripts call ``apiFetch``, ``escapeHtml``, ``showLoadError`` and
``formatDate``. All four live in ``main.js``, which is loaded from the head
with ``defer`` -- it has to be, because it binds its listeners to
``document`` and would otherwise be re-executed on every Turbo navigation,
leaving another copy of every handler behind.

A deferred script runs *after* the document is parsed. An ordinary
``<script src>`` at the end of the body runs *during* parsing. So the
moment ``main.js`` moved to the head, a page script without ``defer``
started running before the file it depends on:

    var resp = await apiFetch(...)       -> ReferenceError
    catch (e) { showLoadError(...) }     -> ReferenceError again

and the second one is thrown out of a ``catch``, so it becomes an unhandled
rejection rather than an error. The table sat on "Loading..." for good, the
console stayed clean, and the whole suite stayed green: this is exactly the
class of defect that a rendered-markup assertion cannot see. It was caught
by ``tests/live/browser_test.py`` and nothing else.

Both attributes are checked together because either alone is a trap. Every
page script deferred while ``main.js`` is not would break the same way
round; this file therefore asserts the order rather than the attribute.
"""

import re
from pathlib import Path

import pytest


TEMPLATES = (
    Path(__file__).resolve().parents[4]
    / "src" / "link_shortener" / "web" / "templates"
)

PAGE_SCRIPT = re.compile(
    r"<script\s+src=\"\{\{ url_for\('static',\s*"
    r"filename='(js/pages/[a-z_]+\.js)'\) \}\}\"([^>]*)>"
)


SCRIPTS = (
    Path(__file__).resolve().parents[4]
    / "src" / "link_shortener" / "web" / "static" / "js" / "pages"
)


def templates_with_page_scripts():
    """
    Every template that loads a page script, found rather than listed.

    A list would go stale the moment a page is added, and the page that is
    added is the one most likely to be written by copying an older one --
    from before this rule existed.
    """
    found = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        for script, attributes in PAGE_SCRIPT.findall(path.read_text()):
            found.append((path.relative_to(TEMPLATES).as_posix(), script,
                          attributes))
    return found


class TestEveryPageScriptIsDeferred:

    def test_every_page_script_on_disk_is_accounted_for(self):
        """
        The guard on the parametrised checks below, and it counts files
        rather than matches on purpose.

        A threshold ("at least seventeen") passes a tag the pattern stopped
        recognising: the parametrised list quietly shrinks by one, every
        remaining case is green, and the page whose script is no longer
        deferred is the one nobody checked. Demonstrated -- rewriting one
        tag with different quoting hid it from the pattern and the whole
        file still passed.

        Comparing against the scripts that actually exist closes that: a
        file the pattern cannot find in any template is a failure naming
        the file.
        """
        on_disk = {path.name for path in SCRIPTS.glob("*.js")}
        loaded = {script.rsplit("/", 1)[-1]
                  for _, script, _ in templates_with_page_scripts()}

        assert on_disk, f"no page scripts found in {SCRIPTS}"
        assert on_disk == loaded, (
            f"page scripts no template appears to load: "
            f"{sorted(on_disk - loaded)}; scripts loaded from a template "
            f"but missing from disk: {sorted(loaded - on_disk)}"
        )

    @pytest.mark.parametrize("template,script,attributes",
                             templates_with_page_scripts())
    def test_it_carries_defer(self, template, script, attributes):
        assert "defer" in attributes, (
            f"{template} loads {script} without `defer`: it will run before "
            f"the deferred main.js in the head, and its first call to "
            f"apiFetch/escapeHtml/showLoadError will throw"
        )


class TestTheSharedScriptsComeFirst:

    @pytest.fixture
    def layout(self):
        return (TEMPLATES / "layout" / "base.html").read_text()

    def test_main_js_is_deferred_in_the_head(self, layout):
        """
        The other half of the order. Deferred scripts run in document
        order, so this one running from the head is what puts it ahead of
        the page scripts at the end of the body.
        """
        head = layout.split("</head>")[0]
        loaded = re.search(
            r"<script\s+src=\"\{\{ url_for\('static',\s*"
            r"filename='js/main\.js'\) \}\}\"([^>]*)>", head)

        assert loaded, "main.js is not loaded from <head>"
        assert "defer" in loaded.group(1), (
            "main.js is in the head without `defer`, so it blocks parsing "
            "-- and the page scripts would still run before it if they are "
            "parsed first"
        )

    def test_turbo_is_deferred_in_the_head_too(self, layout):
        head = layout.split("</head>")[0]
        loaded = re.search(
            r"<script\s+src=\"\{\{ url_for\('static',\s*"
            r"filename='vendor/turbo-[0-9.]+\.js'\) \}\}\"([^>]*)>", head)

        assert loaded, "Turbo is not loaded from <head>"
        assert "defer" in loaded.group(1), "Turbo is loaded without `defer`"

    def test_no_page_script_is_loaded_from_the_head(self, layout):
        """
        The mirror of the rule: a page script in the head would run before
        the body it addresses exists, and its `getElementById` calls would
        all answer null. It also has to be re-executed on navigation --
        the head is the one place Turbo will not do that.
        """
        head = layout.split("</head>")[0]

        assert "js/pages/" not in head
