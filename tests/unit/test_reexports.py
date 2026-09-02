"""
What a package offers outward is what it actually has.

The layers are imported through a facade: ``from link_shortener.domain
import Email``. The facade's list is ``__all__`` in ``__init__.py``, and it
lives apart from the ``from .`` lines above it, so it drifts from them in
silence. A name left in the list after its import was removed breaks no
existing module: an ordinary ``from package import Name`` never reaches the
list at all. What breaks is ``import *``, and anyone who reads the list as
a promise.

Found exactly that way: ``"CacheKeyGenerator"`` sat in the ``__all__`` of
the ``infrastructure`` package with not one import behind it -- and 2426
tests knew nothing about it.
"""

import importlib

import pytest


FACADES = [
    "link_shortener.domain",
    "link_shortener.application",
    "link_shortener.infrastructure",
    "link_shortener.infrastructure.cli",
    "link_shortener.infrastructure.mail",
    "link_shortener.infrastructure.task_queue",
]
"""The packages that have an ``__all__`` and are used as a facade."""


@pytest.mark.parametrize("module_name", FACADES)
def test_every_exported_name_exists(module_name):
    """Every name in ``__all__`` resolves to an object."""
    module = importlib.import_module(module_name)

    missing = [name for name in module.__all__ if not hasattr(module, name)]

    assert not missing, (
        f"{module_name}.__all__ names what the module does not have: {missing}"
    )


@pytest.mark.parametrize("module_name", FACADES)
def test_the_export_list_has_no_repeats(module_name):
    """
    One name, one line of the list.

    A repeat is the trace of two edits merged, and it also hides that one of
    the names has come to mean something else.
    """
    module = importlib.import_module(module_name)
    names = list(module.__all__)

    repeated = sorted({name for name in names if names.count(name) > 1})

    assert not repeated, f"{module_name}.__all__ repeats: {repeated}"


@pytest.mark.parametrize("module_name", FACADES)
def test_a_star_import_succeeds(module_name):
    """
    ``from package import *`` does not fail.

    Kept apart from the check above because it answers the question a reader
    of the documentation asks rather than the one the list's author asks:
    does the form the list exists for actually work. With a broken
    ``__all__`` it raises ``AttributeError`` at import time.
    """
    namespace: dict = {}

    exec(f"from {module_name} import *", namespace)  # noqa: S102

    module = importlib.import_module(module_name)
    assert set(module.__all__) <= set(namespace)
