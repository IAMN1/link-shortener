"""CLI command package. Provides Flask command registration."""

from .adapters.flask import register_flask_commands

__all__ = ["register_flask_commands"]
