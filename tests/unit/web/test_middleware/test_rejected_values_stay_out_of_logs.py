"""
What a failed validation writes down.

``ValidationError.errors()`` carries an ``input`` key holding the value
that was rejected, and pydantic fills it in for every error. The handler
logged that mapping whole, so a password below the length policy went into
``application.log`` in plaintext while the 400 body stayed clean -- the
body is built from ``ErrorDetail``, which never had the value in it.

The assertion looks at every argument of every logger call rather than at
the ``errors`` field by name: the leak is about what reaches the file, not
about which keyword carries it.
"""

from unittest.mock import Mock

import pytest
from flask import Flask
from pydantic import BaseModel, Field

from link_shortener.web.i18n import init_babel
from link_shortener.web.middleware.error_handler import ErrorHandlerMiddleware


SECRET = "sh0rt!"
"""A password an operator must never find in a log file."""


class PasswordRequest(BaseModel):
    """Stands in for the real request models, which constrain the same way."""

    password: str = Field(min_length=8)


@pytest.fixture
def logger():
    """A logger that remembers what it was told."""
    return Mock()


@pytest.fixture
def client(logger):
    """An app whose only route refuses the body it is given."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    # The handler's own sentences are translated now, and `gettext` reads
    # the extension out of `app.extensions`. The real factory wires Babel
    # before any middleware; an app built by hand here has to do the same,
    # or what this measures is `KeyError: 'babel'` instead of a log line.
    app.config["SUPPORTED_LANGUAGES"] = ["en"]
    app.config["DEFAULT_LANGUAGE"] = "en"
    init_babel(app)
    ErrorHandlerMiddleware(app, logger)

    @app.post("/api/v1/probe")
    def probe():
        PasswordRequest(**{"password": SECRET})
        return "unreachable", 200

    return app.test_client()


class TestAValidationFailure:

    def test_the_rejected_value_is_not_logged(self, client, logger):
        response = client.post("/api/v1/probe", json={})

        assert response.status_code == 400
        assert SECRET not in repr(logger.method_calls)

    def test_the_client_is_told_which_field_and_why(self, client):
        """Removing the leak must not remove the diagnosis.

        Without this, dropping the log line altogether -- or emptying the
        response -- would pass the test above.
        """
        response = client.post("/api/v1/probe", json={})
        payload = response.get_json()

        assert payload["error"] == "VALIDATION_ERROR"
        assert payload["details"][0]["field"] == "password"

    def test_the_log_line_still_says_which_field_failed(self, client, logger):
        """The operator needs to see it without the value beside it."""
        client.post("/api/v1/probe", json={})

        recorded = repr(logger.method_calls)

        assert "Validation error" in recorded
        assert "password" in recorded
        assert "string_too_short" in recorded
