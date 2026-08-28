"""
An application built from a configuration object is checked too.

``ConfigFactory.create_config`` calls ``validate()``, so the environment
path was covered -- and that is the path nothing in this suite uses.
Every other place that builds an app passes ``config=``, which went
straight past the checks: an app handed
``DEFAULT_RATE_LIMIT_PERIOD=-60`` came up and throttled nothing at all,
measured at 150 requests out of 150 let through.

The second test here is the one nothing did at all: build the app the way
production does, with no argument, as gunicorn does in the ``Dockerfile``.
"""

import pytest

from link_shortener.infrastructure.configs.app.testing import TestingConfig
from link_shortener.web.app_factory import create_app


def config_with(**overrides):
    """
    Build a testing configuration with fields replaced.

    Args:
        **overrides: Class attributes to set on the subclass.

    Returns:
        An instance detached from the environment.
    """
    return type("Probe", (TestingConfig,), overrides)()


class TestAConfigurationObjectIsValidated:

    def test_a_period_that_disables_throttling_is_refused(self):
        """The measured one: negative period, no throttling, no complaint."""
        with pytest.raises(ValueError, match="DEFAULT_RATE_LIMIT_PERIOD"):
            create_app(config=config_with(DEFAULT_RATE_LIMIT_PERIOD=-60))

    def test_a_scheme_outside_the_two_allowed_is_refused(self):
        with pytest.raises(ValueError, match="Invalid URL scheme"):
            create_app(config=config_with(ALLOWED_SCHEMES=["ftp"]))

    def test_a_sound_configuration_still_builds(self):
        """The refusals must not cost the ordinary case."""
        app = create_app(config=TestingConfig())

        assert app.config["TESTING"] is True


class TestTheWayProductionBuildsIt:
    """``create_app()`` with no argument -- what gunicorn calls.

    Every other caller in the suite passes ``config=``; none took this
    path, so the branch that resolves the profile and validates it was
    reached by nothing under test.
    """

    def test_it_builds_with_no_argument(self, monkeypatch, tmp_path):
        monkeypatch.setenv("FLASK_ENV", "testing")
        monkeypatch.chdir(tmp_path)

        app = create_app()

        # Asserted through a value the profile decides rather than through
        # the profile name: `ENV` is not published into `app.config`, and
        # a test that read it would only be checking its own monkeypatch.
        assert app.config["TESTING"] is True
        assert app.config["DATABASE_URL"] == "sqlite:///:memory:"
