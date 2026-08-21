"""
What a page is allowed to say about a failure, and what gets recorded.

Two faults measured in the same branch of the domain-error handler, both
invisible to a green suite:

  - the page printed ``error.message`` for a 5xx while the API answered
    "An internal error occurred" for the same failure. ``GET /dashboard/``
    with the default role missing put "Default role 'user' is missing from
    the database" on screen -- the sentence the API deliberately withholds,
    naming a part of the deployment to an anonymous caller.

  - the HTML branch returned above ``logger.error``, so a domain failure on
    a page route -- the routes a person is actually looking at -- was
    answered and never recorded. The API path logged it; the page path did
    not, and the operator's evidence depended on which surface tripped.

Both are about the same rule: the page and the envelope answer the same
failure, and neither of them is where an operator reads about it.
"""

from unittest.mock import Mock

import pytest
from flask import Flask

from link_shortener.domain.exceptions import DomainError
from link_shortener.web.i18n import init_babel
from link_shortener.web.middleware.error_handler import ErrorHandlerMiddleware


INTERNAL = "Default role 'user' is missing from the database"
"""A 5xx sentence of the kind that describes the deployment, not the request."""


@pytest.fixture
def logger():
    """A logger that remembers what it was told.

    ``bind`` answers with the same object, so what the handler writes on
    the bound logger is read here without threading a second mock through
    every test: the handler binds the request context before writing, and
    a mock whose ``bind`` returned a fresh child would hide the line
    rather than show it.
    """
    logger = Mock()
    logger.bind.return_value = logger
    return logger


@pytest.fixture
def failing_app(logger, tmp_path):
    """
    An application whose routes fail the way the domain fails.

    Both surfaces are registered on one app because the whole point is
    that the two answer alike; two apps would let a fix land on one.

    Deliberately not named ``app``: ``tests/unit/web/conftest.py`` carries
    an autouse fixture that replaces the template loader of whatever
    ``app`` resolves to with one answering "Rendered <name>" for every
    template. A fixture of that name here inherits the replacement, and
    the checks below -- which read the sentence off the rendered page --
    would then be measuring a stub instead of the page.
    """
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "error.html").write_text("<h1>{{ error }}</h1>", encoding="utf-8")

    application = Flask(__name__, template_folder=str(templates))
    application.config["TESTING"] = True
    application.config["SUPPORTED_LANGUAGES"] = ["en"]
    application.config["DEFAULT_LANGUAGE"] = "en"
    init_babel(application)
    ErrorHandlerMiddleware(application, logger, Mock())

    @application.route("/page")
    def page():
        raise DomainError(INTERNAL, code="CONFIGURATION_ERROR")

    @application.route("/api/v1/thing")
    def thing():
        raise DomainError(INTERNAL, code="CONFIGURATION_ERROR")

    @application.route("/page-refused")
    def refused():
        raise DomainError("You are not allowed to view this link", code="FORBIDDEN")

    return application


class TestAFiveHundredSaysTheSameOnBothSurfaces:

    def test_the_page_does_not_print_the_services_own_state(self, failing_app):
        markup = failing_app.test_client().get("/page").get_data(as_text=True)

        assert INTERNAL not in markup

    def test_the_page_says_what_the_envelope_says(self, failing_app):
        markup = failing_app.test_client().get("/page").get_data(as_text=True)

        assert "An internal error occurred" in markup

    def test_the_envelope_is_unchanged(self, failing_app):
        body = failing_app.test_client().get("/api/v1/thing").get_json()

        assert body["message"] == "An internal error occurred"
        assert body["error"] == "CONFIGURATION_ERROR"

    def test_a_four_hundred_still_says_what_happened(self, failing_app):
        """
        The narrowing is for 5xx alone. A refusal the caller can act on
        has to keep saying what it was, or every wrong answer becomes
        "something went wrong".
        """
        markup = failing_app.test_client().get("/page-refused").get_data(as_text=True)

        assert "You are not allowed to view this link" in markup


class TestTheOperatorHearsAboutItEitherWay:

    def test_a_failure_on_a_page_route_is_recorded(self, failing_app, logger):
        failing_app.test_client().get("/page")

        assert logger.error.called, "the page path answered and logged nothing"

    def test_a_failure_on_an_api_route_is_recorded(self, failing_app, logger):
        failing_app.test_client().get("/api/v1/thing")

        assert logger.error.called

    def test_the_log_line_keeps_the_english_sentence(self, failing_app, logger):
        """
        Not the translated one. ``application.log`` is read by an operator
        who did not choose the visitor's language, and one failure must
        not be two different strings depending on who tripped over it.
        """
        failing_app.test_client().get("/page")

        _args, kwargs = logger.error.call_args

        assert kwargs["error"] == INTERNAL
        assert kwargs["code"] == "CONFIGURATION_ERROR"
