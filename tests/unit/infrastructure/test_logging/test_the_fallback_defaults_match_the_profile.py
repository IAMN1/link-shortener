"""The defaults in ``logging_settings_from`` are the profile's own.

They are a second copy of a truth ``BaseConfig`` already holds, and they
cannot be dropped: ``read`` is handed whatever holds the configuration, and
a name it cannot find has to resolve to something. What can be done is hold
the two copies together, the way ``PERMISSION_FOR`` is held to ``Journal``.

One of the thirteen had already drifted when this was written.
``LOG_FILENAME`` read ``link_shortener`` here and ``application`` there --
the pair that decides which file the application writes and which file the
journal viewer reads, so a configuration object without the attribute would
have written ``link_shortener.log`` while the viewer read ``application.log``
and ``logrotate`` rotated neither.
"""

import pytest

from link_shortener.infrastructure.configs.app.base import BaseConfig
from link_shortener.infrastructure.logging.logging_settings import (
    attribute_reader, logging_settings_from,
)


SHARED = (
    "log_file_name",
    "audit_log_filename",
    "error_log_filename",
    "log_date_format",
    "log_to_console",
    "log_to_file",
    "log_level_str",
    "sqlalchemy_log_level",
    "werkzeug_log_level",
    "logger_type",
    "logging_enabled",
    "audit_enabled",
)
"""The settings both sides state a default for, and must state alike."""

APART = ("log_dir", "debug")
"""The two that differ on purpose, named so that neither is forgotten.

``LOG_DIR`` is a property on the profile: it resolves against
``PROJECT_ROOT``, so the profile answers an absolute path where the
fallback answers ``logs``, and the two cannot be compared as values.

``DEBUG`` is ``True`` on ``BaseConfig``, which is a base a developer
inherits, and ``False`` here, which is what a configuration object missing
the attribute should get. A fallback that switched debug on for a
configuration it could not read would be the wrong way round.
"""


def finds_nothing(_name, default=None):
    """A configuration object that holds none of the names."""
    return default


@pytest.fixture
def detached():
    """The profile read away from this machine's environment.

    ``IGNORE_ENV`` is what ``EnvField`` checks before touching
    ``os.environ``, so every descriptor answers with its own default --
    which is the value being compared here. Without it the test would
    compare the fallback against whatever ``.env`` happens to say, and
    would redden on a machine that configured its journals.
    """
    return type("Detached", (BaseConfig,), {"IGNORE_ENV": True})()


@pytest.mark.parametrize("field", SHARED)
def test_a_name_the_configuration_lacks_resolves_to_the_profile_s_default(
    field, detached
):
    from_nothing = logging_settings_from(finds_nothing)
    from_profile = logging_settings_from(attribute_reader(detached))

    assert getattr(from_nothing, field) == getattr(from_profile, field)


def test_every_setting_is_either_compared_or_named_as_apart():
    """No third category: a setting added later is in one list or the other.

    Without this, a name added to ``logging_settings_from`` alone joins
    neither list and is compared by nothing -- which is the state
    ``LOG_FILENAME`` was in.
    """
    settings = logging_settings_from(finds_nothing)
    named = set(SHARED) | set(APART) | {"raise_on_write_failure"}

    assert set(vars(settings)) - named == set()
