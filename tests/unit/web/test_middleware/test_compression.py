"""
Tests for the response compression middleware.

Nothing in front of this application compresses anything -- gunicorn serves
it directly, with no nginx and no CDN -- so the middleware is the only thing
between a 40 KB stylesheet and the wire. Two of its decisions are easy to
get wrong in a way nothing else notices, and both are checked here: a
response from ``send_file`` looks streamed and used to be skipped, so HTML
compressed and CSS did not; and changing the ETag to name the encoded entity
breaks the conditional request unless the middleware answers it itself.
"""

import gzip
import pathlib

import pytest
from flask import Flask

import link_shortener.web
from link_shortener.web.middleware.compression import CompressionMiddleware


LONG = "linkr " * 400        # comfortably over the threshold, and compressible
SHORT = "linkr"              # under it

# The real asset directory, taken from the package rather than by counting
# parent directories up from this file: the assets are what the middleware
# exists to compress, and a stub would not reproduce the file wrapper that
# `send_file` returns -- which is the whole subtlety being tested.
STATIC = pathlib.Path(link_shortener.web.__file__).parent / "static"


@pytest.fixture
def app():
    """A bare application carrying nothing but the middleware."""

    application = Flask(__name__, static_folder=str(STATIC))
    CompressionMiddleware(application)

    @application.route("/text")
    def text():
        return LONG

    @application.route("/short")
    def short():
        return SHORT

    @application.route("/json")
    def json_body():
        return {"items": [LONG]}

    @application.route("/binary")
    def binary():
        return application.response_class(
            b"\x00\x01" * 2000, mimetype="image/png"
        )

    @application.route("/already")
    def already():
        response = application.response_class(LONG, mimetype="text/plain")
        response.headers["Content-Encoding"] = "br"
        return response

    return application


@pytest.fixture
def client(app):
    return app.test_client()


GZIP = {"Accept-Encoding": "gzip"}


class TestWhatGetsCompressed:

    def test_a_long_text_body_is_compressed(self, client):
        response = client.get("/text", headers=GZIP)

        assert response.headers["Content-Encoding"] == "gzip"
        assert len(response.data) < len(LONG)

    def test_the_bytes_decompress_to_what_was_sent(self, client):
        """The point of the whole thing: the caller must get the body back."""

        response = client.get("/text", headers=GZIP)

        assert gzip.decompress(response.data).decode() == LONG

    def test_json_is_compressed_too(self, client):
        response = client.get("/json", headers=GZIP)

        assert response.headers["Content-Encoding"] == "gzip"

    def test_a_short_body_is_left_alone(self, client):
        """Below the threshold gzip usually makes the body bigger."""

        response = client.get("/short", headers=GZIP)

        assert "Content-Encoding" not in response.headers
        assert response.data.decode() == SHORT

    def test_an_image_is_left_alone(self, client):
        """Already-compressed formats only grow."""

        response = client.get("/binary", headers=GZIP)

        assert "Content-Encoding" not in response.headers

    def test_a_body_somebody_else_encoded_is_not_encoded_again(self, client):
        response = client.get("/already", headers=GZIP)

        assert response.headers["Content-Encoding"] == "br"


class TestWhatTheCallerAskedFor:

    def test_nothing_is_compressed_without_the_header(self, client):
        response = client.get("/text")

        assert "Content-Encoding" not in response.headers
        assert response.data.decode() == LONG

    def test_the_answer_says_it_varies_by_encoding(self, client):
        """
        Without this a shared cache hands a gzipped body to a client that
        never asked for one, and that client cannot read it.
        """

        response = client.get("/text", headers=GZIP)

        assert "Accept-Encoding" in response.headers["Vary"]

    def test_it_says_so_even_when_it_did_not_compress(self, client):
        """The answer varies by encoding whether or not this one did."""

        response = client.get("/text")

        assert "Accept-Encoding" in response.headers["Vary"]

    def test_a_type_it_never_compresses_does_not_claim_to_vary(self, client):
        response = client.get("/binary", headers=GZIP)

        assert "Vary" not in response.headers


class TestStaticFiles:
    """
    The case the middleware exists for, and the one it silently missed.

    A file served by ``send_file`` arrives as a wrapper around an open file
    and reports itself streamed. Asked only whether the response was
    streamed, the middleware returned early on every asset -- so pages
    compressed and the stylesheet they load did not.
    """

    def test_the_stylesheet_is_compressed(self, client):
        response = client.get("/static/css/main.css", headers=GZIP)

        assert response.status_code == 200
        assert response.headers["Content-Encoding"] == "gzip"
        assert len(response.data) < 20_000

    def test_a_repeat_visit_still_gets_a_304(self, client):
        """
        Naming the encoded entity in the ETag is correct and costs a step.

        ``send_file`` compares the caller's ``If-None-Match`` against the tag
        it computes from the file, which is not the tag that went out -- so
        without the middleware answering the conditional request itself,
        every repeat visit came back 200 with the whole body. Compressing an
        asset by 71% while making it arrive on every page load is not a
        saving.
        """

        first = client.get("/static/css/main.css", headers=GZIP)
        etag = first.headers["ETag"]

        second = client.get(
            "/static/css/main.css",
            headers={**GZIP, "If-None-Match": etag},
        )

        assert second.status_code == 304
        assert second.data == b""

    def test_the_font_is_left_alone(self, client):
        """woff2 carries Brotli inside it already."""

        response = client.get(
            "/static/fonts/inter-latin.woff2", headers=GZIP
        )

        assert response.status_code == 200
        assert "Content-Encoding" not in response.headers


class TestStreamedResponses:

    def test_a_generated_body_is_not_drained(self, app, client):
        """
        A response built from a generator is streamed on purpose, and
        reading it here to compress it would defeat that. Only a file
        wrapper, which merely looks streamed, may be read.
        """

        @app.route("/stream")
        def stream():
            return app.response_class(
                (LONG for _ in range(1)), mimetype="text/plain"
            )

        response = client.get("/stream", headers=GZIP)

        assert "Content-Encoding" not in response.headers
        assert response.data.decode() == LONG


class TestAPartOfAFileIsNotAWholeOne:
    """
    ``206 Partial Content`` and compression cannot both be true at once.

    A range response describes bytes of the *identity* body: its
    ``Content-Range`` counts them, and the client reassembles the file
    from the offsets it asked for. Compressing what comes back leaves
    that header describing bytes nobody sent -- and the ETag, being the
    entity's, then names the whole file while the body holds a
    re-encoded slice of it, so a cache can serve the part as the whole.

    Reproduced against Flask's own static route before the fix:
    ``Range: bytes=0-19999`` came back gzipped at ``Content-Length: 93``
    with ``Content-Range`` still claiming twenty thousand bytes.
    """

    def test_a_range_request_comes_back_uncompressed(self, client):
        response = client.get(
            "/static/css/main.css",
            headers={**GZIP, "Range": "bytes=0-19999"},
        )

        assert response.status_code == 206
        assert "Content-Encoding" not in response.headers

    def test_the_range_header_still_describes_the_body_that_arrived(
        self, client
    ):
        """
        The check the header exists for: what it counts is what was sent.
        """
        response = client.get(
            "/static/css/main.css",
            headers={**GZIP, "Range": "bytes=0-99"},
        )

        assert response.status_code == 206
        assert response.headers["Content-Range"].startswith("bytes 0-99/")
        assert len(response.data) == 100

    def test_a_whole_file_is_still_compressed(self, client):
        """
        The rule is about partial answers, not about this file.
        """
        response = client.get("/static/css/main.css", headers=GZIP)

        assert response.status_code == 200
        assert response.headers.get("Content-Encoding") == "gzip"
