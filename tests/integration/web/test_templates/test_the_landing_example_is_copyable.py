"""The `curl` block on the landing page names the address people arrive at.

It is written to be copied, which is the whole reason it exists -- and it
was built from ``request.url_root``: the address *this process* saw the
request come in on. Behind a TLS-terminating proxy that is a plain HTTP
request, whatever the visitor's browser did, so a service reached over
``https://`` printed a command starting ``http://``.

What that costs is not theoretical. A ``POST`` sent to the plain address
either meets a redirect -- and a redirect turns it into a ``GET`` or drops
the body -- or is answered in the clear by whoever is on the path. The
short links the same page hands out were never wrong: they are built from
``BASE_URL``, which is what the example now reads too.

Measured before the change, with ``DOMAIN=maizlink.example``,
``USE_HTTPS=true`` and a request carrying ``X-Forwarded-Proto: https``:

    BASE_URL:            https://maizlink.example
    landing page:        http://maizlink.example/api/v1/shorten
    API short_url:       https://maizlink.example/3tGNeMT
"""

from pathlib import Path

import pytest


TEMPLATE = (
    Path(__file__).resolve().parents[4]
    / "src" / "link_shortener" / "web" / "templates"
    / "public" / "index.html"
)


class TestTheExampleIsBuiltFromTheConfiguredAddress:

    def test_the_template_does_not_ask_the_request_where_it_arrived(self):
        """
        Read from the source rather than from a rendering: the test client
        arrives over http on every profile, so a rendering cannot tell
        ``url_root`` and ``BASE_URL`` apart. The source can.

        The pattern is the *expression*, not the name. The template's own
        comment explains why ``request.url_root`` is not used, and a search
        for the bare name found that sentence and called it a defect.
        """
        source = TEMPLATE.read_text(encoding="utf-8")

        assert "{{ request.url_root" not in source
        assert "{{request.url_root" not in source

    def test_the_example_is_built_from_base_url(self):
        source = TEMPLATE.read_text(encoding="utf-8")

        assert "config.BASE_URL" in source
        assert "/api/v1/shorten" in source


class TestTheRenderedExampleAgreesWithTheLinksTheServiceHandsOut:
    """
    One address, two places on one page: the example a visitor copies and
    the short link the service returns. They are built from the same value
    now, and this is what says so.
    """

    @pytest.mark.parametrize(
        "base_url, expected",
        [
            ("https://maizlink.example", "https://maizlink.example/api/v1/shorten"),
            # ``BASE_URL`` ends with a slash only when it is built from
            # HOST:PORT rather than from DOMAIN, which is why the template
            # strips one rather than trusting the shape.
            ("http://localhost:5000/", "http://localhost:5000/api/v1/shorten"),
        ],
    )
    def test_one_slash_whatever_shape_the_base_url_has(
        self, app, base_url, expected
    ):
        from flask import render_template

        app.config["BASE_URL"] = base_url
        with app.test_request_context("/"):
            markup = render_template("public/index.html")

        assert expected in markup
        assert expected.replace("//api", "/api") in markup
        assert "//api/v1/shorten" not in markup.replace("://", "")
