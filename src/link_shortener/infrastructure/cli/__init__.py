"""Пакет CLI-команд. Предоставляет функцию регистрации для Flask."""

from .adapters.flask import register_flask_commands

__all__ = ["register_flask_commands"]