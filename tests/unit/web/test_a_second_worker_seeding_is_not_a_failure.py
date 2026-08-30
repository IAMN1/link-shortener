"""Two workers seeding the same empty database at once.

`AUTO_SEED_ROLES` runs in every process that builds the application, and a
deployment runs several: the shipped compose file sets `GUNICORN_WORKERS=4`.
The pass is read-then-write -- it looks for the permissions that are missing
and inserts them -- so against an empty database all four look, all four find
the same set missing, and the three that commit second meet the unique index.

Measured on a container with four workers against a fresh PostgreSQL:

    AUTO_SEED_ROLES failed  error=... duplicate key value violates unique
    constraint "permissions_name_key", Key (name)=(link:create) already exists

The outcome was never wrong. Each worker seeds the whole set inside one
transaction, so the winner's commit is complete and the losers roll back
entirely -- the database ends with five roles and fifteen permissions either
way. What was wrong was the sentence: an operator watching a first
deployment reads "AUTO_SEED_ROLES failed" and concludes the roles are
missing, then runs `flask db load-base-roles` to fix something that is not
broken. On a bad day they conclude the deployment is broken and roll it back.

So the clash is told apart from a real failure. An unreachable database, a
refused permission, a malformed YAML file still warn.
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from link_shortener.web import app_factory


class _Logger:
    """Records what was said, at what level."""

    def __init__(self):
        self.said = []

    def info(self, message, **kwargs):
        self.said.append(("info", message, kwargs))

    def warning(self, message, **kwargs):
        self.said.append(("warning", message, kwargs))

    def error(self, message, **kwargs):
        self.said.append(("error", message, kwargs))

    def debug(self, message, **kwargs):
        self.said.append(("debug", message, kwargs))

    def exception(self, message, **kwargs):
        self.said.append(("exception", message, kwargs))


def _container(logger):
    """A container whose schema is in place and whose session works."""
    container = MagicMock()
    container.get_logger.return_value = logger
    manager = MagicMock()
    manager.missing_tables.return_value = []
    container.get_db_manager.return_value = manager
    return container


def _levels(logger):
    return {level for level, _, _ in logger.said}


class TestTheLoserOfTheRaceIsNotReportedAsAFailure:

    def test_a_unique_violation_is_stated_as_what_it_is(self):
        logger = _Logger()
        clash = IntegrityError(
            "INSERT INTO permissions",
            {},
            Exception(
                'duplicate key value violates unique constraint '
                '"permissions_name_key"'
            ),
        )

        with patch.object(app_factory, "seed_base_roles", side_effect=clash):
            app_factory._seed_base_roles_if_ready(_container(logger))

        assert "warning" not in _levels(logger), (
            f"a lost race warned: {logger.said}"
        )
        said = [message for level, message, _ in logger.said if level == "info"]
        assert any("another process" in message for message in said), said

    def test_the_message_carries_what_the_database_said(self):
        """
        Named rather than swallowed: an integrity error that is *not* the
        seeding race -- a foreign key, a check constraint -- reaches the log
        as the database phrased it, so it can be recognised.
        """
        logger = _Logger()
        clash = IntegrityError("INSERT", {}, Exception("permissions_name_key"))

        with patch.object(app_factory, "seed_base_roles", side_effect=clash):
            app_factory._seed_base_roles_if_ready(_container(logger))

        detail = [kwargs for level, _, kwargs in logger.said if level == "info"]
        assert detail and "permissions_name_key" in str(detail[0]), detail


class TestARealFailureStillWarns:
    """
    The clause above must not become a blanket. Everything that is not a
    constraint clash is still the operator's problem to hear about.
    """

    @pytest.mark.parametrize(
        "failure",
        [
            OSError("connection refused"),
            PermissionError("permission denied for table roles"),
            ValueError("roles.yaml: mapping values are not allowed here"),
        ],
        ids=["unreachable", "refused", "malformed-yaml"],
    )
    def test_it_is_reported_as_a_failure(self, failure):
        logger = _Logger()

        with patch.object(app_factory, "seed_base_roles", side_effect=failure):
            app_factory._seed_base_roles_if_ready(_container(logger))

        warned = [message for level, message, _ in logger.said if level == "warning"]
        assert any("AUTO_SEED_ROLES failed" in message for message in warned), (
            logger.said
        )


class TestAnEmptySchemaIsStillNeitherOfThose:
    """The pre-existing third case, kept: no tables yet is a step, not a fault."""

    def test_it_says_what_to_run_next(self):
        logger = _Logger()
        container = _container(logger)
        container.get_db_manager.return_value.missing_tables.return_value = [
            "roles", "permissions",
        ]

        app_factory._seed_base_roles_if_ready(container)

        assert "warning" not in _levels(logger)
        said = [message for level, message, _ in logger.said if level == "info"]
        assert any("not initialised" in message for message in said), said
