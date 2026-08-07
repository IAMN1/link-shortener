"""
Tests that a failing ``after_request`` hook cannot take the response with it.

By the time these hooks run the work is done: the status is decided and the
body is built, and what is left is a header, a cookie or a log line. An
exception there is past every error handler, so Flask falls through to
``handle_exception`` -- which re-raises when ``DEBUG`` or ``TESTING`` is on.
Under ``flask run --debug``, the documented way to run this service in
development, that is the interactive Werkzeug debugger: a full traceback,
locals at every frame, and a console.
"""

from unittest.mock import Mock

import pytest
from flask import Flask

from link_shortener.web.middleware.hooks import response_hook


@pytest.fixture
def logger():
    return Mock()


@pytest.fixture
def app(logger):
    """An app whose only after_request hook raises."""
    application = Flask(__name__)

    @application.route("/x")
    def view():
        return "the answer", 200

    @application.after_request
    @response_hook(logger)
    def explode(response):
        raise RuntimeError("the header could not be built")

    return application


class TestTheResponseSurvives:

    def test_the_answer_still_reaches_the_client(self, app):
        response = app.test_client().get("/x")

        assert response.status_code == 200
        assert response.get_data(as_text=True) == "the answer"

    def test_it_survives_with_testing_on(self, app):
        """
        ``TESTING`` and ``DEBUG`` are what make Flask re-raise, so this is
        the configuration the guard exists for.
        """
        app.config["TESTING"] = True

        assert app.test_client().get("/x").status_code == 200

    def test_the_failure_is_reported(self, app, logger):
        app.test_client().get("/x")

        assert logger.error.called
        assert logger.error.call_args.kwargs["hook"] == "explode"


class TestAWorkingHookIsUntouched:

    def test_its_changes_are_kept(self, logger):
        application = Flask(__name__)

        @application.route("/x")
        def view():
            return "ok", 200

        @application.after_request
        @response_hook(logger)
        def add_header(response):
            response.headers["X-Added"] = "yes"
            return response

        response = application.test_client().get("/x")

        assert response.headers["X-Added"] == "yes"
        assert not logger.error.called
