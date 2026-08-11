"""
Isolation of the suite from the machine it runs on.

Two mechanisms live here, and both address the same failure: a configuration
value reaching a test that no test put there.

``ConfigFactory`` does not merely read ``.env``. It publishes the file's
contents into ``os.environ``, because the field descriptors resolve lazily
and have nowhere else to look. Nothing takes them out again, and
``monkeypatch`` cannot: it restores the variables it set itself, and these
were written by the application code under test.

Measured before this file had any content: a ``.env`` holding the single
line ``GUEST_LINK_LIMIT=-7`` turned a green suite into ``5 failed, 1
error``. One casualty was ``test_production_config_cookie_security``, which
already carried its own ``monkeypatch.chdir`` for precisely this reason --
it passed when run alone and failed when run behind its neighbour. The
neighbour had published the value process-wide before the chdir could
matter.

So the leak has two halves and needs two answers: ``detached_env`` stops a
test reading ``.env`` at all, and ``_restore_environ`` stops whatever does
get published from outliving the test that published it.

``tests/unit/infrastructure/test_config/test_env_precedence.py`` keeps its
own inline copy of the scrubbing rather than using the fixture here. That is
not an oversight: one of its tests has to set a variable **first** and scrub
**afterwards**, to prove the scrubbing removes it, and a fixture always runs
before the test body.
"""

import os
from pathlib import Path
from typing import Iterator

import pytest

from link_shortener.infrastructure.configs.app import factory as config_factory


# ==============================================================================
# What survives a detached test
# ==============================================================================
# An allowlist, not a list of settings to remove. Three attempts at the other
# direction have now missed something in this repository alone:
#
#   * a list of variable names caught DATABASE_URL and missed DATABASE_TYPE,
#     DATABASE_NAME, DATABASE_HOST, DATABASE_USER and DATABASE_PASSWORD;
#   * a list of configuration classes missed CeleryConfig, which declares
#     CELERY_BROKER_TIMEOUT outside the application profiles;
#   * a scan of the EnvField descriptors themselves missed DATABASE_POOL_SIZE,
#     DATABASE_MAX_OVERFLOW and DATABASE_POOL_RECYCLE, which BaseConfig
#     declares as properties reading through read_env instead.
#
# Each miss was the same shape: the configuration grew a way of naming a
# setting that the enumeration did not know about. Inverting it ends that.
# A new setting is covered the moment it exists, whatever idiom declares it,
# and the only thing that ever needs adding here is a variable the test
# machinery itself needs -- which announces itself immediately, as a failure.

KEPT_NAMES = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "PWD", "OLDPWD",
    "TMPDIR", "TEMP", "TMP", "LANG", "TZ", "CI", "SYSTEMROOT",
})
"""Individual variables the interpreter, the shell or the runner needs."""

KEPT_PREFIXES = (
    "PYTEST_", "COV_", "COVERAGE_",
    "PYTHON", "UV_", "VIRTUAL_ENV",
    "LC_", "XDG_", "SSL_CERT_",
    "GITHUB_", "RUNNER_", "ACTIONS_",
    "DOCKER_",
)
"""
Families kept wholesale: the test run itself, the interpreter and its
environment, locale and trust store, the CI runner, and the Docker daemon
the level 2b tests reach.
"""


def _is_kept(name: str) -> bool:
    """
    Tell whether a variable belongs to the machinery rather than the config.

    Args:
        name: Environment variable name.

    Returns:
        ``True`` when the variable must survive into a detached test.
    """
    return name in KEPT_NAMES or name.startswith(KEPT_PREFIXES)


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture(autouse=True)
def _restore_environ() -> Iterator[None]:
    """
    Undo environment changes a test leaves behind, whoever made them.

    Applies to the whole suite. ``monkeypatch`` already covers what a test
    changes itself; this covers what the code under test changes, which is
    the half that actually bit.

    With ``detached_env`` in place this changes no outcome today -- measured.
    It is here for the next module that builds a profile and forgets to
    detach: without it, that module's leak surfaces as a failure somewhere
    else entirely, which is how the original one was found and is a terrible
    way to find anything.

    Only the keys that actually moved are touched, so the environment is
    never momentarily empty -- several tests in this suite run threads, and
    a thread outliving teardown must not observe a process without a PATH.

    What it does not bracket, so nobody reads more into it than it gives:
    anything published before the first snapshot is taken, which means
    during collection or session setup; ``os.putenv`` and ``os.unsetenv``,
    which write past ``os.environ``; and the working directory. Nothing in
    the suite does any of those today.

    Yields:
        Nothing. The environment is repaired after the test.
    """
    before = dict(os.environ)

    yield

    for name in set(os.environ) - set(before):
        del os.environ[name]
    for name, value in before.items():
        if os.environ.get(name) != value:
            os.environ[name] = value


@pytest.fixture()
def detached_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """
    Run a test where no ``.env`` can be found and no setting is inherited.

    Opt in per module with::

        pytestmark = pytest.mark.usefixtures("detached_env")

    Needed wherever a profile other than ``testing`` gets built -- directly,
    or as a side effect of importing something that builds one. Those
    profiles read ``.env``, and the walk upwards from the working directory
    finds a file, which from the repository root means the developer's own.

    Changing the directory is no longer enough on its own.
    ``_read_env_file`` reads the project root before it walks anywhere, and
    that root comes from the location of the configuration module rather
    than from the process -- so it stays the developer's checkout however
    the test is run. Measured when only the ``chdir`` was here:
    ``test_base_url_property`` began reading ``HOST=127.0.0.1`` out of the
    real ``.env`` and expected ``localhost``. The root is therefore pointed
    at the same empty directory.

    Everything outside the allowlist above is removed, so a setting is
    covered regardless of how the configuration happens to declare it.

    Returns:
        The empty directory the test now runs in.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config_factory, "PROJECT_ROOT", tmp_path)
    for name in list(os.environ):
        if not _is_kept(name):
            monkeypatch.delenv(name, raising=False)

    return tmp_path
