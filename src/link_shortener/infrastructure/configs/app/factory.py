import os
import sys
from typing import Dict, Optional

from dotenv import dotenv_values, find_dotenv
from link_shortener.infrastructure.configs.app.base import (
    PROJECT_ROOT, BaseConfig
)
from link_shortener.infrastructure.configs.app.env import is_unset
from link_shortener.infrastructure.configs.app.development import DevelopmentConfig
from link_shortener.infrastructure.configs.app.production import ProductionConfig
from link_shortener.infrastructure.configs.app.staging import StagingConfig
from link_shortener.infrastructure.configs.app.testing import TestingConfig



class ConfigFactory:
    """
    Factory for creating configuration objects
        based on environment name.

    The environment name selects the configuration profile (its class and the
    defaults it declares); a ``.env`` file only overrides individual values
    inside the selected profile. The resulting precedence is:

        real environment variable  >  .env.<profile>  >  .env  >  profile default

    Values are resolved lazily by the descriptors in
    ``link_shortener.infrastructure.configs.app.env``, so a ``.env`` loaded
    here is picked up even though the configuration classes were imported
    earlier.
    """

    CONFIG_MAP = {
        "development": DevelopmentConfig,
        "staging": StagingConfig,
        "production": ProductionConfig,
        "testing": TestingConfig,
    }

    DEFAULT_ENV = "development"
    """Profile used when neither the argument nor FLASK_ENV says otherwise."""

    NO_DOTENV_ENVS = ("testing",)
    """
    Environments that must ignore ``.env`` files.
    Automated tests have to be reproducible on any machine, so they rely only
    on the values hardcoded in ``TestingConfig`` and on explicit monkeypatching.
    ``TestingConfig`` additionally sets ``IGNORE_ENV = True``, which detaches it
    from ``os.environ`` as well – skipping the files alone would not be enough,
    because another profile created earlier in the same process may already
    have loaded them.
    """

    @staticmethod
    def _read_env_file(filename: str) -> Dict[str, str]:
        """
        Read a ``.env``-style file without touching ``os.environ``.

        The project root is tried first, and the walk up from the working
        directory only after it. Searching from the caller alone made the
        configuration depend on where the process happened to be started:
        a celery worker or a bare ``alembic upgrade head`` launched from
        elsewhere found no file and fell back to the profile defaults, so
        ``DATABASE_NAME`` became ``db_shortener`` -- no extension -- while
        the anchoring in ``_sqlite_path`` still put it under the root. A
        second, empty database appeared beside the real one and the service
        came up on it without a word, answering 401 to anonymous shortening
        because the ``guest`` role was only in the other file.

        Outside a source tree there is no root to read from and the walk is
        all there is, which is what an installed copy and the image get.

        Args:
            filename: File name to look for, e.g. ``".env"``.

        Returns:
            Mapping of variable names to values; empty if the file is absent.
        """
        path = ""
        if PROJECT_ROOT is not None:
            candidate = PROJECT_ROOT / filename
            if candidate.is_file():
                path = str(candidate)

        if not path:
            path = find_dotenv(filename, usecwd=True)
        if not path:
            return {}

        return {k: v for k, v in dotenv_values(path).items() if v is not None}

    @staticmethod
    def _dotenv_was_preloaded() -> bool:
        """
        Detect whether the Flask CLI already merged ``.env`` into the process
        environment before the application was imported.

        ``flask`` calls ``load_dotenv()`` in its entry point and marks the run
        with ``FLASK_RUN_FROM_CLI``. Outside that path (gunicorn, ``python -m``,
        celery, alembic) ``os.environ`` still contains only variables the
        operator really exported.

        Returns:
            ``True`` when ``os.environ`` may already contain ``.env`` values.
        """
        return bool(os.environ.get("FLASK_RUN_FROM_CLI"))

    @classmethod
    def _apply_env_files(cls, env: str, shared: Dict[str, str]) -> None:
        """
        Publish the ``.env`` files into ``os.environ`` with the documented
        precedence.

        Values are assigned explicitly instead of relying on
        ``load_dotenv(override=False)``: with a plain ``override=False`` the
        entries the Flask CLI had already injected from ``.env`` would occupy
        the variables and ``.env.<profile>`` could never win, so the precedence
        would silently depend on how the process was started.

        Two regimes therefore apply:

        * **Environment untouched** (gunicorn, ``python``, celery, alembic) –
          anything already present was exported by the operator and always
          wins. No guessing is involved.
        * **Flask CLI** – a variable that holds exactly what ``.env`` says is
          assumed to come from that file and may be overridden by
          ``.env.<profile>``. Only one case stays genuinely ambiguous: an
          exported variable whose value is byte-identical to the ``.env``
          entry. It is indistinguishable from the injected one, because the
          Flask CLI runs before any of this code.

        A blank value counts as unset in both regimes, so an empty ``${VAR}``
        coming from ``docker compose`` falls through to the files instead of
        masking them.

        Args:
            env: Selected profile name.
            shared: Contents of the shared ``.env`` file.
        """
        profile = cls._read_env_file(f".env.{env}")
        preloaded = cls._dotenv_was_preloaded()

        def is_replaceable(key: str) -> bool:
            current = os.environ.get(key)
            if is_unset(current):
                return True
            return preloaded and current == shared.get(key)

        for key, value in profile.items():
            if is_replaceable(key):
                os.environ[key] = value

        for key, value in shared.items():
            if is_unset(os.environ.get(key)):
                os.environ[key] = value

    @classmethod
    def named_env(cls, env: Optional[str] = None) -> Optional[str]:
        """
        Return the profile somebody actually named, if anybody did.

        Separated from ``resolve_env`` because the fallback and a named
        ``development`` are not the same thing to every caller, and the
        resolved name cannot tell them apart. A migration is the caller
        that cares: ``DEFAULT_ENV`` is ``development``, which is also the
        one profile allowed to migrate a database nobody configured, so a
        host where nothing is set would otherwise have the guard disabled
        by the very omission it exists to catch.

        Args:
            env: Explicit profile name, or ``None`` to resolve automatically.

        Returns:
            Normalised (lower-case) profile name, or ``None`` when neither
            the argument, nor the environment, nor ``.env`` names one.
        """
        if env is None or is_unset(env):
            env = os.environ.get("FLASK_ENV")

        if is_unset(env):
            env = cls._read_env_file(".env").get("FLASK_ENV")

        if is_unset(env):
            return None

        return env.strip().lower()

    @classmethod
    def resolve_env(cls, env: Optional[str] = None) -> str:
        """
        Determine which configuration profile to use.

        Order of resolution: explicit argument, ``FLASK_ENV`` from the real
        environment, ``FLASK_ENV`` from ``.env``, then ``DEFAULT_ENV``. The
        ``.env`` lookup matters because the file is the documented place to put
        ``FLASK_ENV``, and outside the Flask CLI nothing else would read it.

        Args:
            env: Explicit profile name, or ``None`` to resolve automatically.

        Returns:
            Normalised (lower-case) profile name.
        """
        named = cls.named_env(env)

        return cls.DEFAULT_ENV if named is None else named

    @classmethod
    def create_config_unvalidated(cls, env: str = None) -> BaseConfig:
        """
        Assemble the configuration object without validating it.

        Split out for ``migration_url.resolve_database_url``, which needs a
        single setting rather than a working application: a migration asks
        for the database URL, and demanding a valid mail server or domain
        of it stopped migrations that would otherwise have run. The profile is
        selected and the ``.env`` files are applied exactly as they are for
        everyone else -- only the final ``validate()`` is left to the
        caller, which is why this is not a way to run the application on a
        configuration that could not pass it.

        Args:
            env: Environment name (development, staging, production, testing).
                 If None, resolved from FLASK_ENV or `.env` (default: development).

        Returns:
            Configuration instance, not yet validated.

        Raises:
            ValueError: If environment is unknown.
        """

        env = cls.resolve_env(env)

        config_class = cls.CONFIG_MAP.get(env)
        if not config_class:
            known = ", ".join(sorted(cls.CONFIG_MAP))
            raise ValueError(f"Unknown environment: {env} (known: {known})")

        if env not in cls.NO_DOTENV_ENVS:
            cls._apply_env_files(env, cls._read_env_file(".env"))

        return config_class()

    @classmethod
    def create_config(cls, env: str = None) -> BaseConfig:
        """
        Create a configuration object for the given environment.

        Args:
            env: Environment name (development, staging, production, testing).
                 If None, resolved from FLASK_ENV or `.env` (default: development).

        Returns:
            Configuration instance.

        Raises:
            ValueError: If environment is unknown, or the configuration does
                not validate.
        """

        config = cls.create_config_unvalidated(env)
        try:
            config.validate()
        except ValueError as error:
            # Said out loud before it is raised. The exception travels out
            # through ``create_app`` and Flask's own ``find_best_app``, so
            # what an operator sees is twenty-five frames of traceback with
            # the useful part at the very bottom -- on a
            # production profile missing DOMAIN. The list is what they
            # need; the frames are what a developer needs, and both stay.
            print(
                f"\n{error}\n\n"
                f"Profile: {cls.resolve_env(env)}. "
                f"Settings come from the environment first, then "
                f".env.<profile>, then .env.\n",
                file=sys.stderr,
            )
            raise
        return config


def get_config(env: str = None) -> BaseConfig:
    """Convenience function to get configuration."""
    return ConfigFactory.create_config(env)
