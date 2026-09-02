"""What goes into a QR code, and what must never.

One decision carries the whole feature: the square encodes the **short**
address and not the destination. A code carrying the destination scans
perfectly and defeats the link -- no click recorded, no expiry honoured,
and deleting the link leaves every printed copy pointing at the target for
good. That is the kind of mistake that is invisible in testing, because
both squares work.

The rest is about the document being usable twice over: embedded in a page,
where it has to scale, and opened on its own, where it has to have a size.
segno writes one or the other, so this module writes both -- and the shape
it patches is the shape a test has to hold, or a future segno silently
produces an image with no size at all.
"""

import re

import pytest

from link_shortener.web.qr import (
    DEFAULT_SCALE, QUIET_ZONE_MODULES, render_svg,
)


SHORT_URL = "https://links.example/aB3xY7z"
DESTINATION = "https://example.com/a/very/long/destination/address"


def decoded(document: bytes) -> str:
    """
    Read a rendered document back as text.

    Args:
        document: What ``render_svg`` returned.

    Returns:
        The SVG source.
    """
    return document.decode("utf-8")


class TestItIsAnSvgDocument:
    """The format, and why it is this one."""

    def test_it_returns_bytes(self):
        """The view hands it to Flask as a body, which takes bytes."""
        assert isinstance(render_svg(SHORT_URL), bytes)

    def test_it_opens_as_svg(self):
        assert decoded(render_svg(SHORT_URL)).startswith("<svg ")

    def test_it_names_the_svg_namespace(self):
        """Without it the file is not an SVG document at all.

        An HTML parser implies the namespace for markup written inline, so
        an `<svg>` with no `xmlns` looks fine embedded in a page. Fetched
        through `<img src>` it is parsed as XML, where nothing implies it,
        and the browser gives up — silently: the request answers `200`,
        the element reports `complete`, and `naturalWidth` is `0`.

        Found by the browser run after the HTTP run had passed. Over HTTP
        the bytes were correct; what was wrong was what they meant.
        """
        assert 'xmlns="http://www.w3.org/2000/svg"' in decoded(
            render_svg(SHORT_URL)
        )

    def test_it_carries_no_xml_declaration(self):
        """An XML declaration inside HTML is a parse error in every browser.

        The document is embedded in a page as well as served on its own,
        so it has to be legal in both places.
        """
        assert "<?xml" not in decoded(render_svg(SHORT_URL))


class TestItIsUsableAtAnySize:
    """Both halves of the opening tag, and what each is for."""

    def test_it_carries_a_viewbox(self):
        """Without it the page that embeds the image cannot resize it."""
        assert 'viewBox="0 0 ' in decoded(render_svg(SHORT_URL))

    def test_it_carries_a_width_and_a_height(self):
        """Without them a browser opening the file alone has no size to use.

        It falls back to a default box and letterboxes the code inside it,
        which is not wrong so much as unusable.
        """
        document = decoded(render_svg(SHORT_URL))

        assert re.search(
            r'<svg xmlns="[^"]+" width="\d+" height="\d+" viewBox=', document
        ), (
            "the opening tag is not the shape this module patches -- segno "
            "may have changed how it writes one"
        )

    def test_the_declared_size_follows_the_scale(self):
        """The number is the module count times the scale, not a constant."""
        document = decoded(render_svg(SHORT_URL))
        width = int(re.search(r'width="(\d+)"', document).group(1))
        modules = int(
            re.search(r'viewBox="0 0 (\d+)', document).group(1)
        )

        assert width == modules * DEFAULT_SCALE

    def test_the_quiet_zone_is_in_the_viewbox(self):
        """A code without its border is one scanners fail to find.

        The border is four modules on each side, so the drawn grid is
        eight modules narrower than the box around it.
        """
        document = decoded(render_svg(SHORT_URL))
        modules = int(re.search(r'viewBox="0 0 (\d+)', document).group(1))

        # The smallest QR symbol is 21 modules across; with the border it
        # cannot be under 29.
        assert modules >= 21 + 2 * QUIET_ZONE_MODULES


class TestTheTitleIsOptionalAndEscaped:
    """What a screen reader announces."""

    def test_a_title_is_written_in(self):
        assert "<title>aB3xY7z</title>" in decoded(
            render_svg(SHORT_URL, title="aB3xY7z")
        )

    def test_without_one_there_is_no_title_element(self):
        assert "<title>" not in decoded(render_svg(SHORT_URL))

    def test_markup_in_a_title_does_not_escape_it(self):
        """The title comes from a short code, which is generated -- but
        the parameter is a string, and a string that reaches markup
        unescaped is a habit worth not forming."""
        document = decoded(render_svg(SHORT_URL, title="<script>x</script>"))

        assert "<script>" not in document


class TestTwoUrlsDrawTwoSquares:
    """The property that makes the encoding worth checking at all."""

    def test_the_same_address_draws_the_same_square(self):
        assert render_svg(SHORT_URL) == render_svg(SHORT_URL)

    def test_a_different_address_draws_a_different_square(self):
        """If this ever fails, the address is not reaching the encoder."""
        assert render_svg(SHORT_URL) != render_svg(SHORT_URL + "a")

    def test_the_destination_does_not_change_the_square(self):
        """Nothing but the argument reaches the code.

        Written out because the failure it guards against -- a renderer
        quietly given the destination somewhere upstream -- produces a
        perfectly valid image, and no test that only checks "is this a QR
        code" would notice.
        """
        assert render_svg(SHORT_URL) != render_svg(DESTINATION)


class TestItSurvivesAwkwardInput:
    """Sizes at the edges of what a short URL can be."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://links.example/a",
            "https://a-rather-long-branded-domain.example.org/aB3xY7z",
            "http://127.0.0.1:5000/aB3xY7z",
            "https://xn--80ak6aa92e.example/aB3xY7z",
        ],
    )
    def test_it_renders(self, url):
        assert decoded(render_svg(url)).startswith("<svg ")
