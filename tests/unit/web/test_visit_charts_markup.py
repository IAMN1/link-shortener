"""
The block the charts are drawn into, and its agreement with the script.

Nothing here executes a chart -- no test-client run can, since the drawing
happens in a browser, and `tests/live/browser_test.py` is where that is
measured. What is checked here is the seam: the template offers spans and
intervals as `data-` attributes, `static/js/charts.js` reads them and
decides what is valid, and the two lists are written in different files in
different languages. A span the template offers and the script rejects is a
button that does nothing, and it fails silently -- the chart simply stays
as it was.
"""

import re
from pathlib import Path

import pytest

from link_shortener.infrastructure.configs.app.testing import TestingConfig
from link_shortener.web.app_factory import create_app


WEB = Path(__file__).resolve().parents[3] / "src" / "link_shortener" / "web"
CHARTS_JS = WEB / "static" / "js" / "charts.js"
TEMPLATES = WEB / "templates" / "dashboard"

STATS_PAGES = {
    "my_stats.html": "mine",
    "service_stats.html": "service",
    "link_stats.html": "mine",
}
"""The pages that carry the charts, and the scope each one asks for.

``link_stats.html`` asks for ``mine`` as well, and passes a code beside it.
That pairing is the page's whole security argument: the service applies the
owner and the code as one condition, so an address carrying somebody else's
code answers with zeroes. A page that asked for the code alone would read
that link's traffic to anyone who guessed it, and the codes are short.
"""


@pytest.fixture
def charts_app():
    """
    A real application, with its real templates.

    Deliberately not named ``app``: ``tests/unit/web/conftest.py`` carries
    an autouse fixture that swaps the Jinja loader for one answering
    "Rendered <name>" to everything, and it takes its argument by that
    name. A test about markup that quietly measured that stub would pass
    whatever the templates said.
    """
    application = create_app(config=TestingConfig())
    with application.app_context():
        yield application


def render_block(application, scope, code=None):
    """
    Render the charts macro on its own.

    Args:
        application: The application whose Jinja environment to use.
        scope: ``mine`` or ``service``.
        code: Short code to narrow to, or ``None`` for the whole scope.

    Returns:
        The rendered markup.
    """
    template = application.jinja_env.get_template("dashboard/_visit_charts.html")
    with application.test_request_context("/"):
        return str(template.make_module({}).visit_charts(scope, code))


def attribute_values(markup, name):
    """
    Every value an attribute takes in a piece of markup, in order.

    Args:
        markup: The rendered markup.
        name: Attribute to collect, without quotes.

    Returns:
        List of the values found.
    """
    return re.findall(rf'{name}="([^"]*)"', markup)


class TestTheBlockCarriesWhatTheScriptLooksFor:
    """
    Every hook `mountVisitCharts` reaches for, present in the markup.

    The script asks for these by attribute and skips what it cannot find,
    so a renamed hook removes a chart without an error anywhere: the panel
    stays empty and the page still loads.
    """

    @pytest.mark.parametrize("page, scope", sorted(STATS_PAGES.items()))
    def test_the_scope_is_the_one_the_page_means(self, charts_app, page, scope):
        markup = render_block(charts_app, scope)

        assert attribute_values(markup, "data-visit-scope") == [scope]

    def test_every_hook_the_script_reads_is_in_the_markup(self, charts_app):
        markup = render_block(charts_app, "mine")
        script = CHARTS_JS.read_text(encoding="utf-8")

        # What the script actually queries for, taken from the script
        # rather than listed here: a hook added there and forgotten in the
        # template is exactly the failure this test is for.
        wanted = set(re.findall(r"\[(data-visit-[a-z-]+)[\]=]", script))
        missing = sorted(hook for hook in wanted if hook not in markup)

        assert wanted, "no hooks were found in charts.js -- the pattern stopped matching"
        assert missing == [], (
            f"charts.js reads these and the template does not offer them: {missing}"
        )

    def test_the_code_is_carried_only_when_there_is_one(self, charts_app):
        """
        `data-visit-code` present on a link's page, absent everywhere else.

        Absent rather than empty: the script sends the attribute straight
        into the query, and `code=` is a code of zero characters, which
        the service is right to refuse. An empty attribute would turn the
        two service-wide pages into a pair of 400s.
        """
        narrowed = render_block(charts_app, "mine", "abc123")
        broad = render_block(charts_app, "service")

        assert attribute_values(narrowed, "data-visit-code") == ["abc123"]
        assert attribute_values(broad, "data-visit-code") == []

    def test_the_script_sends_the_code_with_both_requests(self):
        """
        Both endpoints narrowed, not just the one drawn first.

        The daily chart is fetched by its own call, so a code threaded
        into one query and not the other draws one chart about this link
        and one about the whole account — side by side, with nothing
        saying they differ.
        """
        script = CHARTS_JS.read_text(encoding="utf-8")
        queries = re.findall(r"chartQuery\(\{([^}]*)\}\)", script)

        assert len(queries) == 2, f"expected two requests, found {len(queries)}"
        assert all("code: code" in query for query in queries), queries

    def test_both_breakdowns_have_a_host_and_a_toggle(self, charts_app):
        markup = render_block(charts_app, "service")

        assert sorted(attribute_values(markup, "data-visit-share")) == ["browsers", "devices"]
        assert sorted(attribute_values(markup, "data-visit-shape")) == ["browsers", "devices"]


class TestTheControlsAndTheScriptAgree:
    """
    The spans and the intervals, as written in two places.

    The template draws the buttons because their labels are sentences and
    `gettext` runs there; the script decides which values are legal
    because it is what a stored preference is checked against. Neither
    side can be dropped, so they are compared instead.
    """

    def test_the_spans_are_the_ones_the_script_knows(self, charts_app):
        markup = render_block(charts_app, "mine")
        script = CHARTS_JS.read_text(encoding="utf-8")

        offered = attribute_values(markup, "data-visit-period")
        known = re.findall(r"'(\d+[hd])':\s*\{", script)

        assert sorted(offered) == sorted(known), (
            "a span the buttons offer that the script does not know is a "
            "button that changes nothing"
        )

    def test_the_intervals_are_the_ones_the_script_accepts(self, charts_app):
        markup = render_block(charts_app, "mine")
        script = CHARTS_JS.read_text(encoding="utf-8")

        offered = sorted(int(value) for value in attribute_values(markup, "data-visit-every"))
        listed = re.search(r"CHART_INTERVALS = \[([^\]]*)\]", script)
        accepted = sorted(int(part) for part in listed.group(1).split(","))

        assert offered == accepted

    def test_switching_off_is_offered_and_is_not_the_refresh_button(self, charts_app):
        """
        Two controls that look alike and are not.

        `0` stops the polling; "Refresh now" fetches once. Nothing else on
        the page says which is which, so if the off switch ever stopped
        being offered the page would keep polling with no way to stop it.
        """
        markup = render_block(charts_app, "mine")

        assert "0" in attribute_values(markup, "data-visit-every")
        assert "data-visit-refresh" in markup


class TestThePagesMountTheChartsTheSameWay:
    """
    Both statistics pages, checked against each other.

    They differ by one word, and everything else about them is the same
    question asked of a different scope -- so they share the template. What
    they cannot share is the two lines that include it.
    """

    @pytest.mark.parametrize("page, scope", sorted(STATS_PAGES.items()))
    def test_the_page_draws_the_block_with_its_own_scope(self, page, scope):
        source = (TEMPLATES / page).read_text(encoding="utf-8")

        assert "dashboard/_visit_charts.html" in source
        assert f"charts.visit_charts('{scope}'" in source

    def test_the_link_page_narrows_by_code_and_never_by_code_alone(self):
        """
        The page about one link, and the pairing that makes it safe.

        Its address carries a short code, and short codes are guessable by
        construction — six characters. What keeps that from being a way to
        read a stranger's traffic is that the code is always sent with
        `scope=mine`, which the service applies as one condition with it.
        """
        source = (TEMPLATES / "link_stats.html").read_text(encoding="utf-8")

        assert "charts.visit_charts('mine', short_code)" in source
        assert "charts.visit_charts('service'" not in source

    @pytest.mark.parametrize("page", sorted(STATS_PAGES))
    def test_the_script_is_loaded_from_the_head(self, page):
        """
        `charts.js` in `extra_head`, never in `page_scripts`.

        It owns the polling timer and the `turbo:before-cache` listener
        that clears it. Turbo merges the head and leaves a script it
        already has alone, so a file there runs once per tab; a page
        script is re-executed on every navigation, and each pass would add
        another listener -- turning the cure into the disease it treats.
        """
        source = (TEMPLATES / page).read_text(encoding="utf-8")
        head = source.split("{% block extra_head %}")[1].split("{% endblock %}")[0]
        scripts = source.split("{% block page_scripts %}")[1].split("{% endblock %}")[0]

        assert "js/charts.js" in head
        assert "js/charts.js" not in scripts
