"""
Фикстуры для unit
"""
import pytest

# Маркировка всех тестов unit как unit
def pytest_collection_modifyitems(items):
    for item in items:
        if 'unit' in item.nodeid:
            item.add_marker(pytest.mark.unit)