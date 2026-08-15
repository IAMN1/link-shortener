"""
Keeping one visitor's pages out of the next one's browser.

Measured before this existed: sign in, open the dashboard, sign out, press
Back -- and the previous account's dashboard is redrawn, their address and
their links on screen, with ``transferSize`` zero and no request reaching
the service. The session was gone (reloading that same URL landed on
``/login``), so it was a picture rather than live data. It was still their
picture, on a machine they had just signed out of.

Nothing in the front end can close that. Turbo's own page cache is not
what serves it -- logging out does a full load, which discards everything
Turbo holds -- and neither is bfcache. It is the ordinary HTTP cache, and
the only thing that speaks to it is a header on the response that put the
page there.

``no-store`` rather than ``no-cache``: ``no-cache`` permits the browser to
keep the entity and revalidate it, and history navigation is exactly the
case where it does not revalidate. ``no-store`` says do not keep it at all.
"""

from flask import Flask, Response, g, request


class PrivateCacheMiddleware:
    """
    Marks every response that belongs to an account as unstorable.

    Anonymous responses are left alone: the landing page, the API
    documentation and the short-link redirects carry nothing personal, and
    they are the ones worth caching.
    """

    def __init__(self, app: Flask):
        """
        Args:
            app: Flask application instance.
        """

        self.app = app
        self._register_handlers()

    def _register_handlers(self):
        """Register the after_request hook."""

        @self.app.after_request
        def mark_private(response: Response) -> Response:
            """
            Add ``Cache-Control: no-store`` to an account's responses.

            Args:
                response: The response as the rest of the application left
                    it.

            Returns:
                The same response, marked when it belonged to an account.
            """
            # `g.current_user` is put there by the authentication
            # middleware on every request, so its absence means the caller
            # was anonymous -- or that this ran before authentication did,
            # which is why `get` is used rather than an attribute.
            if getattr(g, "current_user", None) is None:
                return response

            # The stylesheet, the font and the vendored navigation library
            # are the same bytes for everyone, and they are requested on
            # every page. Marked `no-store` for signed-in visitors they
            # would be fetched again on every navigation -- a quarter of a
            # megabyte, to protect files served to anyone who asks.
            if request.endpoint == "static":
                return response

            response.headers["Cache-Control"] = "no-store"
            return response
