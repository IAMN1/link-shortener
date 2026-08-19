"""
The headers that tell a browser what it may do with a page.

A browser decides several things on its own unless the response says
otherwise, and every one of those defaults is more permissive than this
application needs: it will guess a body's type when the declared one looks
wrong, let any site frame the page, send the full address to whatever an
outbound link leads to, and run whatever script ends up in the markup.

The last is what the policy here is really about, and it is why the policy
is written around this application rather than copied. One inline
``<script>`` is served -- the JSON block carrying the translated strings --
so it is admitted by a nonce minted per response and nothing else.
``'unsafe-inline'`` would have covered it in one word and would have made
the whole ``script-src`` decorative: an injected script is inline too.

What this does *not* do is close cross-site scripting. It narrows what a
successful injection can reach, which is a different claim and the honest
one. The consequence that would hurt most -- a script reading the session
-- is closed elsewhere and better, by cookies that carry ``httponly``,
``secure`` and ``samesite="Strict"``.
"""

import secrets

from flask import Flask, Response, g


NONCE_BYTES = 16
"""How much randomness a nonce carries.

128 bits, which is the size CSP Level 3 asks for -- "should be at least 128
bits long before encoding". A nonce is guessed once per page load and the
page is served again on the next request with a new one, so the number that
matters is not how long a guess takes but that guessing is not worth
starting.
"""

POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'nonce-{nonce}'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "object-src 'none'"
)
"""The policy, with one hole in it big enough for one JSON block.

Every directive is ``'self'`` because every asset is this application's
own: the fonts are in ``static/fonts``, Turbo is vendored under
``static/vendor``, and there is no CDN in the path of a page load -- which
was a decision before it was a policy.

``img-src`` also allows ``data:``: the favicon and the inline SVG icons are
written into the markup, and a document's own bytes are not a third party.

``style-src`` is the one directive that keeps ``'unsafe-inline'``, and it
is a measurement rather than a shrug. The charts position a tooltip, size
a bar and colour a swatch by assigning to ``element.style``, which Chromium
reports as an inline style and refuses: run without it, 36 of 45 browser
checks failed and the console filled with *"Applying inline style
violates..."* on every page that draws anything. Removing it for real means
rewriting how the charts draw, which is a change to the charts and not to
this policy. What it costs is the narrow half: an injection that already
runs can style the page. What it does not cost is the wide half --
``script-src`` carries no ``'unsafe-inline'``, so the injection has to run
first, and that is what the nonce is for.

``frame-ancestors 'none'`` says what ``X-Frame-Options`` says, for the
browsers that read the newer of the two; ``base-uri 'none'`` stops an
injection from moving every relative URL on the page by writing a
``<base>``; ``object-src 'none'`` retires the plugin surface.
"""

HEADERS = {
    # A body is what it says it is. Without this a browser may decide a
    # response is a script because it looks like one, whatever the
    # `Content-Type` says.
    "X-Content-Type-Options": "nosniff",
    # Nothing here frames anything, so the answer is the flat one rather
    # than `SAMEORIGIN`.
    "X-Frame-Options": "DENY",
    # A link's own page carries its short code in the address, and the
    # default policy hands the whole URL to any site an outbound link
    # leads to.
    "Referrer-Policy": "same-origin",
    # None of these is asked for anywhere in the application, and a
    # permission not asked for is one worth refusing before it is.
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}
"""The headers that do not vary by response."""


class SecurityHeadersMiddleware:
    """
    Puts the security headers on every response, and mints the nonce.

    Attributes:
        app: The Flask application.
    """

    def __init__(self, app: Flask):
        """
        Args:
            app: Flask application instance.
        """
        self.app = app
        self._register_handlers()

    def _register_handlers(self):
        """Mint a nonce per request, and write the headers after it."""

        @self.app.before_request
        def mint_nonce() -> None:
            """
            Put this request's nonce where the templates can reach it.

            Before the request rather than after, because the markup is
            rendered inside the request and has to carry the same value
            the header will name. A page whose nonce does not match its
            policy is a page whose script is refused, silently, in the
            browser and nowhere else.
            """
            g.csp_nonce = secrets.token_urlsafe(NONCE_BYTES)

        @self.app.after_request
        def add_headers(response: Response) -> Response:
            """
            Add the headers, unless something upstream already set them.

            Args:
                response: The response as the application left it.

            Returns:
                The same response, with the headers on it.
            """
            for name, value in HEADERS.items():
                response.headers.setdefault(name, value)

            # `setdefault` here too: a view that needs its own policy --
            # none does today -- says so by setting one, and this must not
            # overwrite that decision.
            response.headers.setdefault(
                "Content-Security-Policy",
                POLICY.format(nonce=g.get("csp_nonce", "")),
            )
            return response

        @self.app.context_processor
        def offer_nonce() -> dict:
            """
            Make the nonce available to every template as ``csp_nonce``.

            Returns:
                The one name the layout needs.
            """
            return {"csp_nonce": g.get("csp_nonce", "")}
