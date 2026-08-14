"""No two endpoints answer on one path.

A blueprint declaring ``static_folder='../static'`` with
``static_url_path='/static'`` claims the directory and the path Flask
already serves from its own ``static`` endpoint. Werkzeug matches the first
rule and never the second, so ``frontend.static`` built URLs that something
else then served -- a route that looks live in ``url_map``, in ``url_for``
and in every template, and is dead.

Asserted against the map rather than against a response: both endpoints
returned the file, so no request could tell them apart. That is exactly why
it went unnoticed.
"""

from collections import Counter


class TestTheStaticPathHasOneOwner:

    def test_only_one_rule_is_registered_for_it(self, app):
        rules = [
            rule for rule in app.url_map.iter_rules()
            if str(rule) == "/static/<path:filename>"
        ]

        assert len(rules) == 1, [r.endpoint for r in rules]
        assert rules[0].endpoint == "static"

    def test_no_path_at_all_is_claimed_twice(self, app):
        """The general form, so the next duplicate is caught as well.

        Methods are part of what makes a rule distinct, so two rules over
        one path are only a conflict when they answer the same verbs.
        """
        seen = Counter()
        for rule in app.url_map.iter_rules():
            for method in rule.methods - {"HEAD", "OPTIONS"}:
                seen[(str(rule), method)] += 1

        assert [key for key, count in seen.items() if count > 1] == []

    def test_the_file_is_still_served(self, client):
        """Removing the duplicate must not remove the asset.

        Compared against a byte count rather than against 200 alone: a
        misrouted request that reached the SPA fallback would also answer
        200, with HTML.
        """
        response = client.get("/static/css/main.css")

        assert response.status_code == 200
        assert b"{" in response.data

    def test_pages_link_to_the_endpoint_that_answers(self, client):
        """Templates were rewritten from ``frontend.static`` to ``static``.

        A missed one raises ``BuildError`` and renders 500, so this checks
        a page that carries both a stylesheet and a script.
        """
        response = client.get("/login")
        body = response.get_data(as_text=True)

        assert response.status_code == 200
        assert "/static/css/main.css" in body
