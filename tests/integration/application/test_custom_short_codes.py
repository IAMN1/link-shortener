"""
Tests for a short code the caller chooses.

``flask link create --code`` honours the option rather than accepting and
ignoring it, which looks like a custom code and is not one. Three things
have to hold for it: the format
rules (``ShortCode`` already had them), a uniqueness check that does not
quietly substitute a different code, and a list of names the service answers
to itself.

That last one is the part worth stating. The redirect route is
``/<short_code>``, one path segment, shared with every top-level page.
Werkzeug prefers its own static rule, so a link coded ``health`` is not a
hijacked health check -- it is a link that never resolves, handed over as if
it worked.
"""

import uuid

import pytest

from link_shortener.application.context import RequestContext
from link_shortener.domain import LinkCodeTakenError, ValidationError
from link_shortener.domain.policies.reserved_codes import RESERVED_CODES


@pytest.fixture()
def use_case(app):
    with app.app_context():
        yield app.container.get_create_short_link_use_case()


def _url():
    return f"https://example.com/{uuid.uuid4().hex}"


def _context():
    """A CLI context: no address, so no guest quota and no guest expiry."""
    return RequestContext(request_id="cli-create")


class TestACodeTheCallerChose:

    def test_it_is_the_code_the_link_gets(self, use_case):
        result = use_case.execute(_url(), _context(), custom_code="my-code")

        assert result.short_code == "my-code"

    def test_without_one_a_code_is_still_generated(self, use_case):
        result = use_case.execute(_url(), _context())

        assert result.short_code
        assert 6 <= len(result.short_code) <= 10

    @pytest.mark.parametrize(
        "code", ["short", "waytoolongforacode", "has space", "bad!char", "код"]
    )
    def test_a_malformed_code_is_refused(self, use_case, code):
        with pytest.raises(ValidationError):
            use_case.execute(_url(), _context(), custom_code=code)


class TestACodeAlreadyInUse:

    def test_it_is_refused_rather_than_replaced(self, use_case):
        """
        Answering with a different code would look like it worked. The
        caller asked for that one.
        """
        use_case.execute(_url(), _context(), custom_code="taken1")

        with pytest.raises(LinkCodeTakenError):
            use_case.execute(_url(), _context(), custom_code="taken1")

    def test_the_first_link_is_untouched(self, use_case):
        first = use_case.execute(_url(), _context(), custom_code="taken2")

        with pytest.raises(LinkCodeTakenError):
            use_case.execute(_url(), _context(), custom_code="taken2")

        assert first.short_code == "taken2"


class TestNamesTheServiceAnswersToItself:

    @pytest.mark.parametrize("code", sorted(RESERVED_CODES))
    def test_a_reserved_name_is_refused(self, use_case, code):
        with pytest.raises(ValidationError, match="reserved"):
            use_case.execute(_url(), _context(), custom_code=code)

    @pytest.mark.parametrize("code", ["HEALTH", "Health", "Console"])
    def test_changing_the_case_does_not_help(self, use_case, code):
        with pytest.raises(ValidationError, match="reserved"):
            use_case.execute(_url(), _context(), custom_code=code)

    def test_an_ordinary_word_is_still_allowed(self, use_case):
        assert use_case.execute(
            _url(), _context(), custom_code="healthy"
        ).short_code == "healthy"


class TestTheReservedListMatchesTheRealRoutes:
    """
    A route added later must not become a code nobody can use. Only names
    that could be a code count: six to ten characters of the code alphabet,
    so ``/login`` and ``/api`` are out of reach by being too short.
    """

    def test_every_route_that_could_be_a_code_is_reserved(self, app):
        import re

        pattern = re.compile(r"^[a-zA-Z0-9_-]{6,10}$")
        top_level = set()
        for rule in app.url_map.iter_rules():
            segments = [part for part in str(rule).split("/") if part]
            if segments and not segments[0].startswith("<"):
                top_level.add(segments[0])

        collidable = {name for name in top_level if pattern.match(name)}
        missing = {name for name in collidable if name.lower() not in RESERVED_CODES}

        assert not missing, (
            f"these routes could be issued as short codes and are not "
            f"reserved: {sorted(missing)}"
        )
