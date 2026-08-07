"""
The fixture that detaches a test from its machine has to actually detach it.

``detached_env`` is a defence, and an untested defence is one that stops
working quietly. These tests plant the settings a developer's machine -- or
the hostile CI job -- would be carrying, and then check that none of them
reaches the test.

The planting happens at **module** scope on purpose. Higher-scoped fixtures
are set up before function-scoped ones, so the values are already in
``os.environ`` when the detaching runs. Planting them in the test body would
prove nothing: the fixture would have run first, with nothing to remove.

The three pool settings are here deliberately. ``BaseConfig`` declares them
as properties reading through ``read_env`` rather than as ``EnvField``
descriptors, and an earlier version of the fixture derived its scrub list
from the descriptors -- so these three were exactly what it missed. They are
the reason the fixture keeps an allowlist instead.
"""

import os
from pathlib import Path

import pytest

from link_shortener.infrastructure.configs.app.factory import ConfigFactory


pytestmark = pytest.mark.usefixtures("detached_env")


PLANTED = {
    "GUEST_LINK_LIMIT": "1",
    "BATCH_CREATE_LIMIT": "2",
    "SQLALCHEMY_ECHO": "true",
    "DATABASE_POOL_SIZE": "999",
    "DATABASE_MAX_OVERFLOW": "888",
    "DATABASE_POOL_RECYCLE": "777",
}
"""
Settings planted before each test, and the values a detached test must not
see. The first three are what the hostile CI job exports; the last three are
the ones a descriptor scan cannot find.
"""


@pytest.fixture(scope="module", autouse=True)
def planted_settings():
    """
    Put the settings into the environment before the detaching happens.

    Yields:
        Nothing. The previous values are restored afterwards, so the
        planting does not outlive this module.
    """
    before = {name: os.environ.get(name) for name in PLANTED}
    os.environ.update(PLANTED)

    yield

    for name, value in before.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


# ------------------------------------------------------------------
# TestNothingPlantedSurvives
# ------------------------------------------------------------------
class TestNothingPlantedSurvives:
    """Tests that a planted variable is absent from the environment."""

    @pytest.mark.parametrize("name", sorted(PLANTED))
    def test_the_planted_variable_is_gone(self, name):
        """Should not find the variable a moment after it was planted."""
        assert name not in os.environ


# ------------------------------------------------------------------
# TestTheTestRunsOutsideTheRepository
# ------------------------------------------------------------------
class TestTheTestRunsOutsideTheRepository:
    """Tests that no `.env` is reachable from the working directory."""

    def test_the_working_directory_is_the_empty_one(self, detached_env):
        """Should run in the temporary directory the fixture handed back."""
        assert Path.cwd().resolve() == Path(detached_env).resolve()

    def test_the_working_directory_holds_no_env_file(self, detached_env):
        """Should find no `.env` where the loader starts looking."""
        assert not (Path(detached_env) / ".env").exists()


# ------------------------------------------------------------------
# TestTheProfileSeesItsOwnDefaults
# ------------------------------------------------------------------
class TestTheProfileSeesItsOwnDefaults:
    """Tests that a built profile answers with its declared defaults."""

    def test_a_descriptor_backed_setting_keeps_its_default(self):
        """Should ignore the planted limits and use the profile's own."""
        config = ConfigFactory.create_config("development")

        assert config.GUEST_LINK_LIMIT == 10
        assert config.BATCH_CREATE_LIMIT == 100

    def test_a_property_backed_setting_keeps_its_default(self, monkeypatch):
        """
        Should ignore the planted pool sizes.

        ``DATABASE_TYPE`` has to be set here: ``_pool_setting`` returns 0 for
        anything but PostgreSQL, and a test that never reaches ``read_env``
        would pass no matter what the environment held.
        """
        monkeypatch.setenv("DATABASE_TYPE", "postgresql")

        config = ConfigFactory.create_config("development")

        assert config.DATABASE_POOL_SIZE == 20
        assert config.DATABASE_MAX_OVERFLOW == 10
        assert config.DATABASE_POOL_RECYCLE == 3600
