"""The commands that read, sweep and repair what is already stored.

Seven commands here were reachable only by hand: ``link list``, ``link
info``, ``stats refresh``, ``cache clear``, ``maintenance clean-expired``,
``maintenance clean-sessions`` and ``security reset-password``. Four of
them write -- they delete links, delete sessions, empty the cache and
change a password -- and none had a test.

``link delete`` is the one command of this group that did:
``test_link_access.py`` covers deleting a link that exists, so only its
refusal branch is added below.

Each check reads the result back through the repository or the cache rather
than from the printed line. The commands build their wording from what they
were handed: ``link delete`` announces the code it was given, ``clean-expired``
prints the count the use case returned, and ``reset-password`` says
"successfully" before anything is read back, so output alone cannot tell a
write that happened from one that did not.
"""

from datetime import datetime, timedelta, timezone

import pytest
from flask.testing import FlaskCliRunner
from sqlalchemy import text

from link_shortener.domain.entities.refresh_session import RefreshSession
from link_shortener.domain.entities.user import User
from link_shortener.domain.value_objects.email import Email
from link_shortener.domain.value_objects.password_hash import PasswordHash
from link_shortener.domain.value_objects.short_code import ShortCode
from link_shortener.infrastructure.configs.app.testing import TestingConfig
from link_shortener.infrastructure.database.manager import DatabaseManager
from link_shortener.infrastructure.database.seed import seed_base_roles


class MaintenanceConfig(TestingConfig):
    """Testing profile with the in-memory cache switched on.

    ``cache clear`` and ``stats refresh`` are about the cache, and with
    caching off the container hands out a null implementation that accepts
    every call and keeps nothing -- both commands would pass with their
    bodies deleted.
    """

    LOGGING_ENABLED = False
    AUDIT_ENABLED = False
    AUTO_SEED_ROLES = False
    CACHE_ENABLED = True
    REDIS_ENABLED = False


@pytest.fixture
def database():
    """A database with the schema and the base roles in place."""
    manager = DatabaseManager(
        database_url=MaintenanceConfig.DATABASE_URL,
        echo=False,
        database_type="sqlite",
    )
    manager.connect()
    manager.create_tables()
    with manager.session() as session:
        seed_base_roles(session)

    yield manager
    manager.close()


@pytest.fixture
def app(database):
    """Application bound to that database."""
    from link_shortener.web.app_factory import create_app

    application = create_app(config=MaintenanceConfig())
    application.container.db_component._manager = database
    return application


@pytest.fixture
def runner(app):
    """CLI runner bound to the app."""
    return FlaskCliRunner(app)


def _create_link(runner, app, url, code=None):
    """Shorten a URL through the CLI and return the code it got."""
    args = ["link", "create", "--url", url]
    if code is not None:
        args += ["--code", code]
    result = runner.invoke(app.cli, args)
    assert result.exit_code == 0, result.output
    return code


def _stored_codes(app):
    """Codes of the links currently in the database."""
    with app.app_context():
        with app.container.get_uow_factory()(read_only=True) as uow:
            return {link.short_code.value for link in uow.links.get_recent(limit=100)}


def _set_clicks(app, code, clicks):
    """Put a specific click count on a stored link.

    Counting clicks by asking for redirects would work, but the counter is
    written by a background task and the command under test reads the row,
    so the count is set here rather than waited for.
    """
    with app.app_context():
        with app.container.get_db_manager().session() as session:
            session.execute(
                text("UPDATE urls SET clicks = :clicks WHERE short_code = :code"),
                {"clicks": clicks, "code": code},
            )
            session.commit()


def _make_user(app, address, password_hash="hashed-password"):
    """Write an account straight into the database and return its id."""
    with app.app_context():
        with app.container.get_uow_factory()() as uow:
            role = uow.roles.get_by_name("user")
            user = User.create(
                email=Email(address),
                password_hash=PasswordHash(password_hash),
                roles=[role],
            )
            saved = uow.users.save(user)
            uow.commit()
            return saved.id


class TestLinkCommands:
    """``link list``, ``link info`` and ``link delete``."""

    def test_list_names_every_stored_link_with_its_clicks(self, runner, app):
        """Each code appears, and the click count printed is the stored one.

        The count is set to something no fixture produces on its own:
        against a freshly created link every counter is zero, so a command
        printing a constant zero -- or a constant anything -- would pass a
        check written around what the fixture already made.
        """
        _create_link(runner, app, "https://example.com/one", "cli-one")
        _create_link(runner, app, "https://example.com/two", "cli-two")
        _set_clicks(app, "cli-one", 7)
        _set_clicks(app, "cli-two", 3)

        result = runner.invoke(app.cli, ["link", "list"])

        assert result.exit_code == 0, result.output
        assert "cli-one - 7 clicks" in result.output
        assert "cli-two - 3 clicks" in result.output

    def test_list_says_so_when_there_is_nothing(self, runner, app):
        """An empty database is reported, not printed as an empty table."""
        result = runner.invoke(app.cli, ["link", "list"])

        assert result.exit_code == 0, result.output
        assert "No links found" in result.output

    def test_info_shows_what_is_stored(self, runner, app):
        """Destination, clicks and creation date come from the row.

        Every field is checked against a value the row actually carries: a
        card built from constants, or from the entity as it looked before
        anything was stored, would otherwise pass. The clicks are moved off
        zero for the same reason -- zero is what the fixture leaves.
        """
        _create_link(runner, app, "https://example.com/destination", "cli-info")
        _set_clicks(app, "cli-info", 42)
        with app.app_context():
            with app.container.get_uow_factory()(read_only=True) as uow:
                stored = uow.links.find_by_code(ShortCode("cli-info"))

        result = runner.invoke(app.cli, ["link", "info", "cli-info"])

        assert result.exit_code == 0, result.output
        assert "https://example.com/destination" in result.output
        assert "Clicks: 42" in result.output
        assert stored.created_at.isoformat() in result.output
        assert "Last accessed: never" in result.output

    def test_info_refuses_an_unknown_code(self, runner, app):
        """A code nobody has is an error, not an empty card."""
        result = runner.invoke(app.cli, ["link", "info", "absent0"])

        assert result.exit_code == 1
        assert "not found" in result.output

    # Deleting a link that exists is checked by
    # ``test_link_access.py::test_the_cli_deletes_without_asking``, which
    # also pins that the CLI passes ``enforce_ownership=False``. Only the
    # branch it does not reach is here.
    def test_delete_refuses_an_unknown_code(self, runner, app):
        """Deleting what is not there exits non-zero."""
        result = runner.invoke(app.cli, ["link", "delete", "absent0"])

        assert result.exit_code == 1
        assert "not found" in result.output


class TestCacheCommands:
    """``stats refresh`` and ``cache clear``, which is what empties it."""

    def test_refresh_recomputes_rather_than_reprinting_the_cache(
        self, runner, app
    ):
        """The command drops the cached entry before asking for the figures.

        Not dropped, the use case answers from the cache, and the command
        prints stale numbers under the words "REFRESHED IN CACHE". The
        check is written so that the command has to do the dropping: a
        stale entry is planted first, and it is the command's job to
        replace it.
        """
        _create_link(runner, app, "https://example.com/counted", "cli-stat")
        with app.app_context():
            app.container.get_cache().save_stats(
                {
                    "total_urls": 999,
                    "total_clicks": 999,
                    "avg_clicks_per_url": 1.0,
                    "popular_links": [],
                }
            )

        result = runner.invoke(app.cli, ["stats", "refresh"])

        assert result.exit_code == 0, result.output
        assert "Total URL's: 1" in result.output
        with app.app_context():
            cached = app.container.get_cache().get_stats()
        assert cached is not None
        assert cached["total_urls"] == 1, "the stale entry should be gone"

    def test_clear_with_stats_only_keeps_the_links(self, runner, app):
        """The statistics entry goes and the link entries stay.

        Both halves are checked because the flag is the only thing that
        separates this command from the one below: a body ignoring
        ``--stats-only`` passes any check that looks at the statistics
        alone.
        """
        _create_link(runner, app, "https://example.com/cached", "cli-cache")
        runner.invoke(app.cli, ["link", "info", "cli-cache"])
        runner.invoke(app.cli, ["stats", "refresh"])
        with app.app_context():
            cache = app.container.get_cache()
            assert cache.get_stats() is not None
            with app.container.get_uow_factory()(read_only=True) as uow:
                cache.save(uow.links.find_by_code(ShortCode("cli-cache")))
            assert cache.get_by_code(ShortCode("cli-cache")) is not None

        result = runner.invoke(app.cli, ["cache", "clear", "--stats-only"])

        assert result.exit_code == 0, result.output
        with app.app_context():
            cache = app.container.get_cache()
            assert cache.get_stats() is None
            assert cache.get_by_code(ShortCode("cli-cache")) is not None

    def test_clear_empties_the_whole_cache(self, runner, app):
        """Without the flag the link entries go as well as the statistics."""
        _create_link(runner, app, "https://example.com/full", "cli-full")
        runner.invoke(app.cli, ["stats", "refresh"])
        with app.app_context():
            cache = app.container.get_cache()
            with app.container.get_uow_factory()(read_only=True) as uow:
                cache.save(uow.links.find_by_code(ShortCode("cli-full")))
            assert cache.get_by_code(ShortCode("cli-full")) is not None

        result = runner.invoke(app.cli, ["cache", "clear"])

        assert result.exit_code == 0, result.output
        with app.app_context():
            cache = app.container.get_cache()
            assert cache.get_stats() is None
            assert cache.get_by_code(ShortCode("cli-full")) is None
        # The links themselves are untouched: this empties a cache, not a
        # database, and an operator running it must not lose data.
        assert "cli-full" in _stored_codes(app)


class TestMaintenanceSweeps:
    """``clean-expired`` and ``clean-sessions``: the two periodic deletions."""

    def test_expired_links_go_and_live_ones_stay(self, runner, app):
        """The sweep is keyed on the expiry, not on age or on count."""
        _create_link(runner, app, "https://example.com/keeps", "cli-live")
        _create_link(runner, app, "https://example.com/expires", "cli-dead")
        with app.app_context():
            with app.container.get_uow_factory()() as uow:
                from link_shortener.domain.value_objects.short_code import ShortCode

                doomed = uow.links.find_by_code(ShortCode("cli-dead"))
                doomed.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
                uow.links.save(doomed)
                uow.commit()

        result = runner.invoke(app.cli, ["maintenance", "clean-expired"])

        assert result.exit_code == 0, result.output
        assert "Deleted 1 expired links" in result.output
        codes = _stored_codes(app)
        assert "cli-live" in codes
        assert "cli-dead" not in codes

    def test_expired_sessions_go_and_live_ones_stay(self, runner, app):
        """A refresh session outlives its token by nothing."""
        user_id = _make_user(app, "sweeper@example.com")
        now = datetime.now(timezone.utc)
        with app.app_context():
            with app.container.get_uow_factory()() as uow:
                uow.refresh_sessions.save(
                    RefreshSession.create(
                        user_id=user_id,
                        token_id="token-expired",
                        expires_at=now - timedelta(hours=1),
                    )
                )
                uow.refresh_sessions.save(
                    RefreshSession.create(
                        user_id=user_id,
                        token_id="token-live",
                        expires_at=now + timedelta(hours=1),
                    )
                )
                uow.commit()

        result = runner.invoke(app.cli, ["maintenance", "clean-sessions"])

        assert result.exit_code == 0, result.output
        assert "Deleted 1 expired refresh sessions" in result.output
        with app.app_context():
            with app.container.get_uow_factory()(read_only=True) as uow:
                assert uow.refresh_sessions.find_by_token_id("token-expired") is None
                assert uow.refresh_sessions.find_by_token_id("token-live") is not None


class TestPasswordReset:
    """``security reset-password``: the way in when nobody can sign in."""

    def test_the_stored_hash_changes(self, runner, app):
        """The account carries a different hash afterwards, and it verifies."""
        _make_user(app, "locked-out@example.com")
        with app.app_context():
            with app.container.get_uow_factory()(read_only=True) as uow:
                before = uow.users.find_by_email(
                    Email("locked-out@example.com")
                ).password_hash.value

        result = runner.invoke(
            app.cli,
            [
                "security",
                "reset-password",
                "--email",
                "locked-out@example.com",
                "--password",
                "NewPassword123!",
            ],
        )

        assert result.exit_code == 0, result.output
        with app.app_context():
            after = None
            with app.container.get_uow_factory()(read_only=True) as uow:
                after = uow.users.find_by_email(
                    Email("locked-out@example.com")
                ).password_hash.value
            assert after != before
            assert app.container.get_authentication_service().verify_password(
                "NewPassword123!", after
            )

    def test_an_unknown_address_is_refused(self, runner, app):
        """Nothing is written for an account that does not exist."""
        result = runner.invoke(
            app.cli,
            [
                "security",
                "reset-password",
                "--email",
                "nobody@example.com",
                "--password",
                "NewPassword123!",
            ],
        )

        assert result.exit_code == 1
        assert "not found" in result.output
