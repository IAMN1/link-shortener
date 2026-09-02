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

One header here is conditional. ``Strict-Transport-Security`` answers a
question the others do not: not what a loaded page may do, but whether the
*next* visit is allowed to start in the clear. ``COOKIE_SECURE`` already
keeps the session off a plain connection, so nothing leaks -- but the
first request of a later visit is still made over ``http://`` and can
still be answered by whoever is on the path. It is sent only where
``USE_HTTPS`` says there is TLS to insist on, and ``HSTS_MAX_AGE`` carries
the reasoning about its value.
"""

import secrets

from flask import Flask, Response, current_app, g


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

``style-src`` is the one directive that keeps ``'unsafe-inline'``, and the
reason was measured rather than assumed. Chromium refuses an assignment to
``element.style`` under a strict ``style-src``, CSSOM or not, and two
things in every page do exactly that. Turbo's progress bar is the wider of
the two: ``turbo-8.0.23.js`` sets ``progressElement.style.width`` and
``.opacity`` and inserts a ``<style>`` of its own, on every navigation of
every page. The charts are the second: a tooltip's position, a bar's width
and a swatch's colour are all assignments to ``element.style``.

Measured twice, and the second time after the templates had been cleaned
of every ``style="..."`` attribute: without ``'unsafe-inline'`` the browser
run still failed, and the console still filled with *"Applying inline style
violates..."* on ``/login`` and ``/register``, which draw no chart at all.
So the markup was never the whole of it, and removing the allowance means
giving up Turbo's progress bar and rewriting how the charts draw.

What it costs is the narrow half: an injection that already runs can
restyle the page. What it does not cost is the wide half -- ``script-src``
carries no ``'unsafe-inline'``, so an injection has to run first, and that
is what the nonce is for.

``frame-ancestors 'none'`` says what ``X-Frame-Options`` says, for the
browsers that read the newer of the two; ``base-uri 'none'`` stops an
injection from moving every relative URL on the page by writing a
``<base>``; ``object-src 'none'`` retires the plugin surface.
"""

POLICY_WITHOUT_SCRIPT = POLICY.format(nonce="").replace(" 'nonce-'", "")
"""The same policy for a response that rendered no template.

Built once at import. A static file, a redirect or a JSON error carries no
markup, so there is no inline script to admit and no nonce to name -- and
naming one anyway describes an allowance nothing on that response could
use. Measured: the policy with a nonce in it is 241 bytes, this one is
210, so a nonce named on a body with no markup is 31 bytes on every asset
of every page load, spent to admit an inline script that is not there.
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

            # Only where the service is actually served over TLS. Sent from
            # a plain-HTTP origin the header is ignored by every browser,
            # which makes it harmless and useless at once -- and on a
            # development run it would be the one header that outlives the
            # run, since a browser that accepted it once refuses plain
            # `http://localhost` afterwards for as long as the max-age says.
            max_age = current_app.config.get("HSTS_MAX_AGE", 0)
            if current_app.config.get("USE_HTTPS") and max_age:
                response.headers.setdefault(
                    "Strict-Transport-Security", f"max-age={max_age}"
                )

            # `setdefault` here too: a view that needs its own policy --
            # none does today -- says so by setting one, and this must not
            # overwrite that decision.
            #
            # A response that rendered no template asked for no nonce, and
            # naming one there would be 31 bytes of header describing an
            # allowance nothing can use -- see `POLICY_WITHOUT_SCRIPT`,
            # which is what such a response carries instead. Most requests
            # in a page load are exactly that: `base.html` references five
            # static assets, and a redirect's body is werkzeug's own stub.
            minted = g.get("csp_nonce")
            response.headers.setdefault(
                "Content-Security-Policy",
                POLICY.format(nonce=minted) if minted else POLICY_WITHOUT_SCRIPT,
            )
            return response

        @self.app.context_processor
        def offer_nonce() -> dict:
            """
            Mint this response's nonce, for the template that asks.

            Minted here rather than in a ``before_request`` because only a
            rendered page can carry one: the header written afterwards
            reads the same value out of ``g``, so the two cannot disagree,
            and a response with no markup pays neither the randomness nor
            the bytes.

            Returns:
                The one name the layout needs.
            """
            if "csp_nonce" not in g:
                g.csp_nonce = secrets.token_urlsafe(NONCE_BYTES)

            return {"csp_nonce": g.csp_nonce}
