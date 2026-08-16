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
            # Said before the `no-store` branch below, because it is the
            # anonymous pages -- the ones deliberately left cacheable --
            # that need it. Measured before these lines existed: `/` renders
            # `data-theme="dark"` or nothing at all depending on a cookie,
            # carries no `Cache-Control`, and said it varied by
            # `Accept-Encoding` alone. A shared cache had every right to
            # hand one visitor's page to the next.
            #
            # Both names, because a page is built from both. The cookie
            # carries the theme, the collapsed sidebar and the chosen
            # language; `Accept-Language` decides the language when no
            # cookie has been set, which is the state most first visits are
            # in. Naming only the cookie would leave a cache free to answer
            # an English browser with the page it stored for a Russian one.
            #
            # Pages that were actually drawn, which is narrower than
            # "text/html": `redirect()` answers `text/html` too, so a plain
            # content-type test also caught the short-link redirects -- the
            # most cacheable thing the service has, built from neither a
            # cookie nor a language. Marking those would spend the caching
            # this middleware exists to protect, and it is what the first
            # version of this line did until a test said so.
            #
            # The redirect anonymous visitors get from `/dashboard/` does
            # depend on a cookie and is left unmarked deliberately: a 302 is
            # not in the list of statuses a cache may store on its own
            # judgement (RFC 9110, 15.1), so there is nothing to tell.
            drawn_a_page = (
                200 <= response.status_code < 300
                and (response.content_type or "").lower().startswith("text/html")
            )
            # The API answers in a language too, now that `message` is
            # translated: the same `/api/v1/links/nosuch` gives "Link not
            # found" or "Ссылка не найдена" depending on the cookie the
            # browser sent with it. Anonymous API answers are as cacheable
            # as anonymous pages, so without this a shared cache may hand
            # one caller's language to the next -- the same fault as on the
            # pages above, on a surface that is easier to cache.
            #
            # Every status, not just 2xx: the refusals are exactly the
            # answers whose `message` is a sentence, and a 404 is storable
            # on a cache's own judgement (RFC 9110, 15.1) where a 302 is
            # not.
            speaks_a_language = (response.content_type or "").lower().startswith(
                "application/json"
            )
            if drawn_a_page or speaks_a_language:
                response.vary.add("Cookie")
                response.vary.add("Accept-Language")
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
