"""
A short link as a square somebody can point a camera at.

A QR code is a *representation* of the short URL and nothing more: it
carries no information the address does not, and it is produced from a
string this layer already knows how to build. So it lives here, beside the
other ways an answer is shaped, rather than behind a port -- there is no
decision for an adapter to make and no second implementation to swap in.

SVG rather than PNG, and no size parameter on the request. A QR code is a
grid of squares, which is what vector graphics are for: one document
prints on a poster and renders in a table cell. A raster would need a size
on the way in, an imaging library to produce it, and a rule about which
sizes to allow.

Error correction is left at the library's default (``M``, about 15 %).
Higher levels buy tolerance of a damaged or partly covered code at the
cost of a denser grid, and the codes here are short -- a seven-character
path on a domain -- so the grid stays small enough to scan from a phone
across a desk.
"""

import io
from typing import Optional

import segno


#: The border, in modules, mandated by the QR specification. Four is the
#: quiet zone a scanner needs to find the code's edges; below it, readers
#: begin to fail on a code printed against a busy background. Named rather
#: than left to the library's default so that a later change is a decision
#: rather than a version bump.
QUIET_ZONE_MODULES = 4

#: Pixels per module in the ``width``/``height`` the document declares.
#: Only the *default* size: the ``viewBox`` beside it means a page can ask
#: for any other by setting a width, and the shape scales rather than
#: stretching. Eight puts a seven-character code at about 260 px, which is
#: large enough to scan off a screen and small enough for a table cell.
DEFAULT_SCALE = 8

_SVG_OPEN = '<svg xmlns="http://www.w3.org/2000/svg" viewBox='


def render_svg(url: str, title: Optional[str] = None) -> bytes:
    """
    Render a URL as an SVG QR code.

    The document carries both a ``viewBox`` and a ``width``/``height``,
    which segno writes one or the other of. Both are needed and for
    different readers: without the ``viewBox`` the image cannot be resized
    by the page that embeds it, and without ``width``/``height`` it has no
    intrinsic size, so a browser opening the file on its own falls back to
    a default box and letterboxes the code inside it.

    Args:
        url: The address to encode. This is the *short* URL -- the thing a
            reader should end up visiting -- and never the destination: a
            code carrying the destination would bypass the counters, the
            expiry and the deletion the short link exists to provide.
        title: Optional ``<title>`` for the document, which is what a
            screen reader announces and what a browser shows on hover.

    Returns:
        The SVG document, encoded as UTF-8 bytes.
    """
    code = segno.make_qr(url)

    # Written through `save` rather than `svg_inline`, and the difference
    # is one attribute. `svg_inline` drops both the XML declaration *and*
    # the namespace, which is right for markup pasted into HTML and wrong
    # for a file: an `<svg>` with no `xmlns` is not an SVG document, and a
    # browser loading it through `<img src>` parses it as XML and gives up.
    # It fails silently -- the request answers `200`, the element reports
    # `complete`, and `naturalWidth` is 0. Found by the browser run; the
    # HTTP run cannot see it, because over HTTP the bytes are correct.
    #
    # `xmldecl=False` all the same: the document is embedded in a page as
    # well as fetched, and an XML declaration inside HTML is a parse error
    # in every browser. `svgclass`/`lineclass` are dropped because the
    # stylesheet has no rules for them -- an unstyled class attribute is
    # bytes on every request that decide nothing.
    buffer = io.BytesIO()
    code.save(
        buffer,
        kind="svg",
        border=QUIET_ZONE_MODULES,
        omitsize=True,
        xmldecl=False,
        svgns=True,
        svgclass=None,
        lineclass=None,
        title=title,
    )
    document = buffer.getvalue().decode("utf-8")

    width, _ = code.symbol_size(scale=DEFAULT_SCALE, border=QUIET_ZONE_MODULES)

    # One replacement against a prefix this module asked for by passing
    # `omitsize=True`, and a test holds the shape: if a future segno stops
    # opening the document this way, the size is missing rather than
    # wrong, and the test says so.
    document = document.replace(
        _SVG_OPEN,
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width}" height="{width}" viewBox=',
        1,
    )

    return document.encode("utf-8")
