"""
The service as it is worked from a shell.

Work comes here when an operator has to be able to start it themselves --
seeding, sweeping, rolling up, diagnosing -- as against work a request
starts. Split by who owns the terminal: ``commands`` does the work and
returns what it did, ``adapters`` declares the options, prints the answer
and settles the exit code.
"""

from .adapters.flask import register_flask_commands

__all__ = ["register_flask_commands"]
