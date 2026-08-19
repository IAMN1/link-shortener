"""The headers a browser needs to be told, and the policy behind them.

None of these were sent. The consequence that matters most was closed
another way -- the session cookies carry `httponly`, `secure` and
`samesite="Strict"`, so a script that ran on a page could not read them or
send them anywhere -- but a browser decides several things on its own
unless a response says otherwise, and each of them was left to the default:

* whether to guess a body's type when the declared one looks wrong,
* whether another site may frame this one,
* how much of the current address to leak in `Referer`,
* and what a page is allowed to load and execute at all.

The last is the one with teeth, and the one that has to be shaped around
the page rather than merely turned on: this application serves one inline
`<script>` -- the JSON block that carries the translated strings -- so the
policy admits a per-response nonce and nothing else. `'unsafe-inline'`
would have been the cheap answer and would have declared the policy void
for exactly the case it exists to stop.
"""

import re

import pytest


PAGES = ["/", "/login", "/register"]
"""Pages a browser is served. The policy has to hold on every one."""

# What the nonce does to the *markup* is checked in
# `tests/integration/web/test_security_headers_reach_the_page.py`, not
# here: the unit fixture replaces every template with a stub, so a check
# reading the rendered page passes here whatever the page says.


class TestEveryResponseCarriesTheHeaders:

    @pytest.mark.parametrize("path", PAGES)
    def test_the_type_is_not_guessed(self, client, path):
        """
        Without `nosniff` a browser may decide a body is a script because
        it looks like one, whatever the `Content-Type` says. An upload
        endpoint is the usual way that is reached; this service has none,
        which makes the header cheap rather than unnecessary.
        """
        assert client.get(path).headers["X-Content-Type-Options"] == "nosniff"

    @pytest.mark.parametrize("path", PAGES)
    def test_the_page_may_not_be_framed(self, client, path):
        """
        `DENY`, not `SAMEORIGIN`: nothing here frames anything.
        """
        assert client.get(path).headers["X-Frame-Options"] == "DENY"

    @pytest.mark.parametrize("path", PAGES)
    def test_the_address_does_not_travel_to_other_sites(self, client, path):
        """
        A short link's own page carries the code in its address, and the
        default policy sends the full URL to any site an outbound link
        leads to.
        """
        assert client.get(path).headers["Referrer-Policy"] == "same-origin"

    def test_the_api_is_covered_too(self, client):
        """
        Not only the pages. A JSON body read by a browser is still a body a
        browser can be talked into treating as something else.
        """
        response = client.get("/api/v1/links/nothing-here")

        assert response.headers["X-Content-Type-Options"] == "nosniff"


class TestThePolicyIsShapedAroundThisApplication:

    @pytest.mark.parametrize("path", PAGES)
    def test_a_policy_is_sent(self, client, path):
        assert "Content-Security-Policy" in client.get(path).headers

    @pytest.mark.parametrize("path", PAGES)
    def test_nothing_may_be_loaded_from_another_origin(self, client, path):
        """
        `default-src 'self'` with no host allowed beside it. Every asset
        this application serves is its own -- the fonts are in
        `static/fonts`, and Turbo is vendored under `static/vendor`
        precisely so that no CDN is in the path of a page load.
        """
        policy = client.get(path).headers["Content-Security-Policy"]

        assert "default-src 'self'" in policy
        assert "https://" not in policy

    @pytest.mark.parametrize("path", PAGES)
    def test_inline_script_is_admitted_by_nonce_and_not_by_blanket(
        self, client, path
    ):
        """
        The page carries one inline block and it must be named, not
        excused. `'unsafe-inline'` in `script-src` is the cheap answer and
        it is the same as having no script policy at all.

        Asserted on the directive rather than on the whole header, because
        `style-src` does keep `'unsafe-inline'` and says why: the charts
        position and colour their elements through `element.style`, which
        Chromium refuses as an inline style. That is the narrow half of
        the policy. This is the wide one.
        """
        policy = client.get(path).headers["Content-Security-Policy"]
        scripts = [
            directive for directive in policy.split(";")
            if directive.strip().startswith("script-src")
        ]

        assert len(scripts) == 1, policy
        assert "'unsafe-inline'" not in scripts[0], scripts[0]
        assert "'unsafe-eval'" not in scripts[0], scripts[0]
        assert re.search(r"'nonce-[A-Za-z0-9_-]+'", scripts[0]), scripts[0]

    def test_each_response_gets_its_own_nonce(self, client):
        """
        A nonce reused across responses is a constant, and a constant an
        attacker can read off one page and write into their injection.
        """
        first = client.get("/").headers["Content-Security-Policy"]
        second = client.get("/").headers["Content-Security-Policy"]

        assert first != second
