"""
Lazy environment-backed configuration fields.

Configuration classes declare their values with the helpers from this module
instead of calling ``os.environ.get()`` directly in the class body.

A direct call in a class body is evaluated at **import time**, which happens
before ``ConfigFactory.create_config()`` calls ``load_dotenv()``. As a result
every value coming from ``.env`` was silently ignored and the class default
was used instead.

The descriptor below reads the environment at **attribute access** time, so
the resolution order is always:

    real environment variable  >  .env.<profile>  >  .env  >  profile default

Usage::

    class BaseConfig:
        GUEST_LINK_LIMIT: int = env_int("GUEST_LINK_LIMIT", 10)
        CORS_ORIGINS: list = env_list("CORS_ORIGINS", ["http://localhost:5000"])

Subclasses may still override a field with a plain literal (e.g.
``TestingConfig.SECRET_KEY = "test-secret-key"``). A plain attribute shadows
the descriptor, which is what deterministic test configuration needs.

A configuration class can also opt out of the environment completely by
setting ``IGNORE_ENV = True``; every inherited field then returns its default.
``TestingConfig`` uses this so a stray ``DATABASE_URL`` in the developer's
shell cannot redirect the test suite at a real database.
"""

import os
from typing import Any, Callable, List, Optional, cast


# ==========================================================================
# Casters
# ==========================================================================
TRUE_VALUES = ("true", "1", "yes", "on")
"""
Raw string values that are interpreted as boolean ``True``.
Comparison is case-insensitive and ignores surrounding whitespace.
"""

FALSE_VALUES = ("false", "0", "no", "off")
"""
Raw string values that are interpreted as boolean ``False``.

Anything outside ``TRUE_VALUES`` and ``FALSE_VALUES`` raises instead of
silently becoming ``False`` – a typo such as ``SQLALCHEMY_ECHO=truthy`` must
not quietly disable a setting.
"""


def to_bool(raw: str) -> bool:
    """
    Convert a raw environment string to a boolean.

    Args:
        raw: Raw value read from the environment.

    Returns:
        ``True`` for ``TRUE_VALUES``, ``False`` for ``FALSE_VALUES``.

    Raises:
        ValueError: If the value is neither, so typos surface immediately.
    """
    normalized = raw.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False

    raise ValueError(
        f"expected one of {', '.join(TRUE_VALUES + FALSE_VALUES)}, got {raw!r}"
    )


def to_list(raw: str) -> List[str]:
    """
    Convert a comma-separated environment string to a list.

    Empty items are dropped, surrounding whitespace is stripped, so
    ``"a, b ,"`` becomes ``["a", "b"]``.

    Args:
        raw: Raw value read from the environment.

    Returns:
        List of non-empty string items.
    """
    return [item.strip() for item in raw.split(",") if item.strip()]


def is_unset(raw: Optional[str]) -> bool:
    """
    Tell whether a raw environment value counts as "not configured".

    ``None`` and blank strings are both treated as unset. ``docker compose``
    substitutes an empty string for every ``${VAR}`` missing from the env file,
    so a blank must behave like an absent variable rather than like a
    deliberate empty setting.

    Args:
        raw: Raw value read from the environment, or ``None``.

    Returns:
        ``True`` when the value carries no configuration.
    """
    return raw is None or not raw.strip()


def read_env(name: str, default: Any = None) -> Any:
    """
    Read a single environment variable applying the blank-is-unset rule.

    Intended for ``@property`` bodies that cannot be expressed as a plain
    ``EnvField`` because they carry extra logic (conditional defaults,
    mandatory-value checks). Using it keeps those properties consistent with
    the descriptors instead of re-implementing ``os.environ.get`` semantics.

    Args:
        name: Name of the environment variable.
        default: Value returned when the variable is unset or blank.

    Returns:
        The raw string value, or ``default``.
    """
    raw = os.environ.get(name)

    return default if is_unset(raw) else raw


# ==========================================================================
# Descriptor
# ==========================================================================
class EnvField:
    """
    Descriptor that resolves a configuration value from the environment.

    The value is looked up on every attribute access, never cached, so a
    ``.env`` file loaded after the module was imported is still honoured.

    Attributes:
        name: Name of the environment variable to read.
        default: Value returned when the variable is not set.
        caster: Callable converting the raw string to the target type.
    """

    def __init__(self, name: str, default: Any, caster: Callable[[str], Any]):
        """
        Args:
            name: Name of the environment variable to read.
            default: Value returned when the variable is not set.
            caster: Callable converting the raw string to the target type.
        """
        self.name = name
        self.default = default
        self.caster = caster

    def __get__(self, instance: Any, owner: Optional[type] = None) -> Any:
        """
        Read and convert the value from the environment.

        Works both on an instance (``config.PORT``) and on the class
        (``BaseConfig.PORT``), because configuration values never depend on
        instance state.

        The environment is ignored entirely when the owning configuration
        class sets ``IGNORE_ENV = True`` (see ``TestingConfig``).

        A variable set to an empty or whitespace-only string counts as **not
        set**: ``docker compose`` substitutes an empty string for every
        ``${VAR}`` that is missing from the env file, and ``PORT=`` must not
        turn into a crash instead of the documented default.

        Returns:
            The converted environment value, or ``default`` if unset.

        Raises:
            ValueError: If the raw value cannot be converted to the target type.
        """
        if owner is not None and getattr(owner, "IGNORE_ENV", False):
            return self.default

        raw = os.environ.get(self.name)
        if is_unset(raw):
            return self.default

        try:
            return self.caster(raw)
        except (TypeError, ValueError) as e:
            raise ValueError(
                f"Invalid value for environment variable {self.name}: {raw!r} ({e})"
            ) from e

    def __repr__(self) -> str:
        return f"EnvField({self.name!r}, default={self.default!r})"


# ==========================================================================
# Typed helpers
# ==========================================================================
# Each helper returns an EnvField at runtime but is annotated with the target
# type, so declarations keep their natural annotations (``PORT: int = ...``)
# and remain readable for static analysis.
# ==========================================================================
def env_str(name: str, default: Optional[str] = None) -> str:
    """
    Declare a string configuration field backed by an environment variable.

    Args:
        name: Name of the environment variable.
        default: Value used when the variable is not set.

    Returns:
        A lazily resolved string field.
    """
    return cast(str, EnvField(name, default, str))


def env_int(name: str, default: int) -> int:
    """
    Declare an integer configuration field backed by an environment variable.

    Args:
        name: Name of the environment variable.
        default: Value used when the variable is not set.

    Returns:
        A lazily resolved integer field.
    """
    return cast(int, EnvField(name, default, int))


def env_float(name: str, default: float) -> float:
    """
    Declare a float configuration field backed by an environment variable.

    Args:
        name: Name of the environment variable.
        default: Value used when the variable is not set.

    Returns:
        A lazily resolved float field.
    """
    return cast(float, EnvField(name, default, float))


def env_bool(name: str, default: bool) -> bool:
    """
    Declare a boolean configuration field backed by an environment variable.

    Accepted true values are listed in ``TRUE_VALUES``; anything else is
    treated as ``False``.

    Args:
        name: Name of the environment variable.
        default: Value used when the variable is not set.

    Returns:
        A lazily resolved boolean field.
    """
    return cast(bool, EnvField(name, default, to_bool))


def env_list(name: str, default: List[str]) -> List[str]:
    """
    Declare a list configuration field backed by an environment variable.

    The environment value is a comma-separated string, e.g.
    ``CORS_ORIGINS="https://a.example,https://b.example"``.

    Args:
        name: Name of the environment variable.
        default: Value used when the variable is not set.

    Returns:
        A lazily resolved list field.
    """
    return cast(List[str], EnvField(name, default, to_list))
