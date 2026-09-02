"""
Holds the vendored copy of Turbo to the release it claims to be.

A vendored file is a dependency that no dependency manager is watching.
Nothing here resolves it, nothing pins it, and `uv.lock` has never heard of
it -- so an edit to it, an accidental truncation by a half-finished
download, or a swap for a different build would travel with the repository
unremarked. The checksum is the only thing standing where a lockfile stands
for everything else.

The figure is the SHA-256 of `dist/turbo.es2017-umd.js` inside the npm
package `@hotwired/turbo` at 8.0.23, and it can be reproduced from the
published artifact without trusting this repository:

    curl -sL https://registry.npmjs.org/@hotwired/turbo/-/turbo-8.0.23.tgz \\
      | tar xzO package/dist/turbo.es2017-umd.js | shasum -a 256

The UMD build rather than the ESM one because it is loaded by a plain
`<script src>` tag; there is no bundler here to resolve a module. The
package ships no minified build, which is why the file is 212 KB -- it
leaves compressed, at 45 KB, by the middleware that compresses everything
else.
"""

import hashlib
from pathlib import Path

import pytest


VENDOR = (
    Path(__file__).resolve().parents[4]
    / "src" / "link_shortener" / "web" / "static" / "vendor"
)

TURBO = VENDOR / "turbo-8.0.23.js"

TURBO_SHA256 = "f9e09e3a3093874fe56d5341ca3594ac959f8b097c9b6171a5b37838da3aec81"


class TestTheVendoredTurboIsTheReleaseItSaysItIs:

    def test_the_file_is_present(self):
        """
        Named first, because every other check here would be an error
        rather than a failure without it, and an error says less.
        """
        assert TURBO.is_file(), f"{TURBO} is missing"

    def test_the_checksum_matches_the_published_release(self):
        digest = hashlib.sha256(TURBO.read_bytes()).hexdigest()

        assert digest == TURBO_SHA256, (
            "the vendored Turbo is not the published 8.0.23 artifact; "
            "if it was deliberately replaced, update TURBO_SHA256 and say "
            "in the commit which release it now is"
        )

    def test_nothing_else_moved_into_the_vendor_directory_unrecorded(self):
        """
        The directory holds third-party code, which is the code least
        likely to be read and most likely to matter. A second file
        appearing here should be a decision, not a surprise.
        """
        found = sorted(p.name for p in VENDOR.iterdir() if p.is_file())

        assert found == [TURBO.name], (
            f"unrecorded files in static/vendor: {found}"
        )


class TestTheLayoutLoadsTheFileThatIsActuallyThere:
    """
    A checksum on a file nothing loads proves nothing. These tie the
    vendored artifact to the markup that asks for it, so a rename on one
    side without the other is a failure rather than a page whose navigation
    quietly stops working.
    """

    @pytest.fixture
    def layout(self):
        templates = (
            Path(__file__).resolve().parents[4]
            / "src" / "link_shortener" / "web" / "templates"
        )
        return (templates / "layout" / "base.html").read_text()

    def test_the_layout_asks_for_the_vendored_filename(self, layout):
        assert f"vendor/{TURBO.name}" in layout

    def test_it_is_loaded_from_the_head(self, layout):
        """
        Not decoration: Turbo merges the head across navigations and skips
        a script it already has, so a script there runs once per tab. The
        same file at the end of `<body>` is re-executed on every
        navigation, and `main.js` binds to `document` -- which survives the
        swap. Moved down, every navigation would leave another copy of
        every handler behind.
        """
        head = layout.split("</head>")[0]

        assert f"vendor/{TURBO.name}" in head, "Turbo is loaded outside <head>"
        assert "js/main.js" in head, "main.js is loaded outside <head>"
