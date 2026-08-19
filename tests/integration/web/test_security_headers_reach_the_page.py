"""The nonce in the header against the nonce in the page.

The half of the policy that cannot be checked over stubbed templates. The
unit fixture in `tests/unit/web/conftest.py` replaces every template with
a one-line stub, so a check reading the rendered markup there passes
whatever the markup says -- which is exactly the check that matters here:
a page carrying a nonce the header does not name is a page whose script the
browser refuses, silently, and nothing on the server would say so.

The style attributes are checked here for the same reason. `style-src
'self'` refuses `style="..."` as well as `<style>`, and a refused style
attribute renders as an unstyled element rather than as an error.
"""

import re

import pytest


PAGES = ["/", "/login", "/register", "/verify"]
"""Pages served to a browser, rendered from the real templates."""


class TestTheNonceIsTheSameOnBothSides:

    @pytest.mark.parametrize("path", PAGES)
    def test_the_page_carries_the_nonce_its_policy_names(self, client, path):
        response = client.get(path)
        policy = response.headers["Content-Security-Policy"]
        markup = response.get_data(as_text=True)

        named = re.search(r"'nonce-([A-Za-z0-9_-]+)'", policy)

        assert named, policy
        assert f'nonce="{named.group(1)}"' in markup, path

    @pytest.mark.parametrize("path", PAGES)
    def test_every_inline_script_carries_it(self, client, path):
        """
        One inline block is admitted by name; a second one added later and
        left without a nonce would simply not run.
        """
        markup = client.get(path).get_data(as_text=True)

        inline = [
            tag for tag in re.findall(r"<script\b[^>]*>", markup)
            if " src=" not in tag
        ]

        assert inline, f"{path} carries no inline script at all"
        assert all("nonce=" in tag for tag in inline), inline


class TestThePagesCarryNoStyleThePolicyRefuses:

    @pytest.mark.parametrize("path", PAGES)
    def test_no_style_attribute_survives_in_the_markup(self, client, path):
        markup = client.get(path).get_data(as_text=True)

        assert 'style="' not in markup, path

    @pytest.mark.parametrize("path", PAGES)
    def test_no_style_block_survives_either(self, client, path):
        markup = client.get(path).get_data(as_text=True)

        assert "<style" not in markup, path
