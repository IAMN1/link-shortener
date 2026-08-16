import gzip

from flask import Flask, Response, request


COMPRESSIBLE_TYPES = (
    "text/",
    "application/json",
    "application/javascript",
    "application/manifest+json",
    "image/svg+xml",
)
"""What is worth compressing.

Everything else the service sends is already compressed and would only grow:
``woff2`` carries Brotli inside it, and a PNG is a deflate stream with a
header. Matched on the prefix because a content type arrives with its
charset attached -- ``text/html; charset=utf-8``.
"""

MINIMUM_BYTES = 1024
"""Below this, compressing costs more than it saves.

A gzip member has an 18-byte frame of its own, and a few hundred bytes of
JSON often comes out larger than it went in. The figure is the usual one and
is not tuned to anything here.
"""


class CompressionMiddleware:
    """
    Compresses text responses the caller said it could decompress.

    Nothing in front of this application compresses anything: it is served
    by gunicorn directly, with no nginx and no CDN in the picture, and
    whoever runs it may not put one there either. So the stylesheet went out
    at 38 KB and the vendored navigation library at 211 -- more than twice
    the size of everything else the frontend is made of -- for want of a
    header the browser had already asked for.

    Deliberately without a logger, unlike its neighbours: it has nothing to
    report. A compressed response is not an event, and a failure to compress
    one is not either -- the caller gets the body regardless.
    """

    def __init__(self, app: Flask, minimum_bytes: int = MINIMUM_BYTES,
                 level: int = 6):
        """
        Args:
            app: Flask application instance.
            minimum_bytes: Bodies smaller than this are sent as they are.
            level: gzip level. Six is the zlib default and sits where the
                curve bends; nine costs noticeably more processor for about
                a percent of size, which is a poor trade on a synchronous
                worker that a request holds for its whole duration.
        """

        self.app = app
        self.minimum_bytes = minimum_bytes
        self.level = level
        self._register_handlers()

    def _register_handlers(self):
        """Register the after_request hook.

        Registered before every other middleware, because Flask runs
        after_request handlers in reverse: this one has to see the body
        after everybody else has finished writing it.
        """

        @self.app.after_request
        def compress(response: Response) -> Response:
            """
            Compress the body, when that is both possible and worth doing.

            Args:
                response: The response as the rest of the application left it.

            Returns:
                The same response, its body replaced when it was compressed.
            """
            content_type = (response.content_type or "").lower()
            if not content_type.startswith(COMPRESSIBLE_TYPES):
                return response

            # Said whether or not this particular answer was compressed. A
            # shared cache that skips this hands a gzipped body to a client
            # that never asked for one, and the client cannot read it.
            #
            # `vary.add`, not `headers.setdefault`: this hook runs last of
            # all the `after_request` hooks -- Flask runs them in reverse
            # registration order and compression is registered first -- so
            # by the time it gets here another hook has already written a
            # `Vary` of its own. `setdefault` would find the header present
            # and say nothing, dropping `Accept-Encoding` from a response
            # that really does vary by it. Plain assignment has the mirror
            # fault: it would drop whatever the other hook put there.
            response.vary.add("Accept-Encoding")

            if "gzip" not in request.headers.get("Accept-Encoding", "").lower():
                return response

            # A 304 has no body to compress, and a response somebody has
            # already encoded must not be encoded twice.
            if response.status_code < 200 or response.status_code in (204, 304):
                return response
            if response.headers.get("Content-Encoding"):
                return response

            # Two different things look alike here, and telling them apart
            # is the difference between compressing the stylesheet and
            # silently skipping it.
            #
            # A file from `send_file` arrives as a wrapper around an open
            # file, which reports itself streamed; switching passthrough off
            # reads it into memory, which is exactly what is wanted for a
            # 40 KB asset. A response built from a generator is streamed for
            # real, and draining it here would defeat the point of streaming
            # it. Asked only about `is_streamed`, this returned early on
            # every static file -- so HTML compressed and CSS did not, which
            # was the whole reason for the middleware.
            if response.direct_passthrough:
                response.direct_passthrough = False
            elif response.is_streamed:
                return response

            body = response.get_data()
            if len(body) < self.minimum_bytes:
                return response

            packed = gzip.compress(body, self.level)
            # A body that grew is a body sent as it was. It happens on
            # anything already dense, and refusing here costs nothing.
            if len(packed) >= len(body):
                return response

            response.set_data(packed)
            response.headers["Content-Encoding"] = "gzip"

            # The entity changed, so a validator that identifies the plain
            # body must not identify this one as well.
            #
            # And having changed it, this has to answer for it. `send_file`
            # compares the caller's `If-None-Match` against the tag it
            # computes from the file itself, which no longer matches the one
            # sent out -- so every repeat visit came back 200 with the whole
            # body where it used to come back 304 with none. Compressing the
            # stylesheet by 70% while making it arrive on every single page
            # load is not a saving.
            if "ETag" in response.headers:
                etag = response.headers["ETag"]
                response.headers["ETag"] = (
                    etag[:-1] + '-gzip"' if etag.endswith('"') else etag + "-gzip"
                )
                # Werkzeug turns this into a 304 when the tag matches, and
                # leaves it alone when it does not.
                response.make_conditional(request)
            return response
