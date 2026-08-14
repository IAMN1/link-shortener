"""
Что пакеты выставляют наружу, то у них и есть.

Слои импортируются по фасаду: ``from link_shortener.domain import Email``.
Список фасада — ``__all__`` в ``__init__.py``, и он живёт отдельно от
строк ``from .`` над ним, поэтому расходится с ними молча. Имя, оставшееся
в списке после того, как импорт убрали, не ломает ни один существующий
модуль: обычный ``from пакет import Имя`` до списка не доходит вовсе.
Ломается только ``import *`` и всякий, кто прочтёт список как обещание.

Найдено ровно так: ``"CacheKeyGenerator"`` лежал в ``__all__`` пакета
``infrastructure``, а импорта под него не было ни одного — и 2426 тестов
об этом не знали.
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
"""Пакеты, у которых есть ``__all__`` и которыми пользуются как фасадом."""


@pytest.mark.parametrize("module_name", FACADES)
def test_every_exported_name_exists(module_name):
    """Каждое имя из ``__all__`` разрешается в объект."""
    module = importlib.import_module(module_name)

    missing = [name for name in module.__all__ if not hasattr(module, name)]

    assert not missing, (
        f"{module_name}.__all__ называет то, чего в модуле нет: {missing}"
    )


@pytest.mark.parametrize("module_name", FACADES)
def test_the_export_list_has_no_repeats(module_name):
    """
    Одно имя — одна строка списка.

    Повтор — след слияния двух правок, и он же скрывает, что одно из имён
    стало значить другое.
    """
    module = importlib.import_module(module_name)
    names = list(module.__all__)

    repeated = sorted({name for name in names if names.count(name) > 1})

    assert not repeated, f"{module_name}.__all__ повторяет: {repeated}"


@pytest.mark.parametrize("module_name", FACADES)
def test_a_star_import_succeeds(module_name):
    """
    ``from пакет import *`` не падает.

    Отдельно от проверки выше, потому что отвечает на вопрос, который
    задаёт читатель документации, а не автор списка: работает ли форма,
    ради которой список и заведён. Со сломанным ``__all__`` она даёт
    ``AttributeError`` в момент импорта.
    """
    namespace: dict = {}

    exec(f"from {module_name} import *", namespace)  # noqa: S102

    module = importlib.import_module(module_name)
    assert set(module.__all__) <= set(namespace)
