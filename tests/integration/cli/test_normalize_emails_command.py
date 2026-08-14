"""The command that lowers addresses written before normalisation.

``Email`` lowers what it holds, which fixes the future and strands the
past: an account stored as ``Case@Example.com`` is no longer found by a
lookup for it. Its owner cannot sign in, and registering the address again
finds nothing and creates a second account for the same mailbox. This
command is the way out, so these tests hold what it does and -- more
importantly -- what it refuses to do.

The rows are written with SQL rather than through the repository, because
the repository cannot produce them any more: ``Email`` would lower them on
the way in. The read path is a different matter -- ``Email.from_storage``
rebuilds a row exactly as stored -- so the command reads with SQL for its
own reason, which is that it wants two columns for every account in one
pass rather than paged ``User`` aggregates.
"""

import pytest
from flask.testing import FlaskCliRunner
from sqlalchemy import text

from link_shortener.infrastructure.configs.app.testing import TestingConfig
from link_shortener.infrastructure.database.manager import DatabaseManager
from link_shortener.infrastructure.database.seed import seed_base_roles


HASH = "$2b$12$" + "x" * 53


class NormaliseConfig(TestingConfig):
    """Testing profile with its own database file."""

    LOGGING_ENABLED = False
    AUDIT_ENABLED = False
    AUTO_SEED_ROLES = False


@pytest.fixture
def db_manager():
    """A database with the schema in place, fresh for each test."""
    manager = DatabaseManager(
        database_url=NormaliseConfig.DATABASE_URL,
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
def app(db_manager):
    """Application bound to that database."""
    from link_shortener.web.app_factory import create_app

    application = create_app(config=NormaliseConfig())
    application.container.db_component._manager = db_manager
    return application


@pytest.fixture
def runner(app):
    """CLI runner bound to the app."""
    return FlaskCliRunner(app)


def _store(app, *addresses):
    """Write accounts with the addresses exactly as given."""
    with app.app_context():
        with app.container.get_db_manager().session() as session:
            for index, address in enumerate(addresses):
                session.execute(
                    text(
                        "INSERT INTO users "
                        "(id, email, password_hash, is_active, "
                        " email_verified, created_at) "
                        "VALUES (:id, :email, :hash, 1, 1, CURRENT_TIMESTAMP)"
                    ),
                    {"id": f"u{index}", "email": address, "hash": HASH},
                )
            session.commit()


def _store_more(app, user_id, address):
    """Write one more account, without disturbing the ids already used."""
    with app.app_context():
        with app.container.get_db_manager().session() as session:
            session.execute(
                text(
                    "INSERT INTO users "
                    "(id, email, password_hash, is_active, "
                    " email_verified, created_at) "
                    "VALUES (:id, :email, :hash, 1, 1, CURRENT_TIMESTAMP)"
                ),
                {"id": user_id, "email": address, "hash": HASH},
            )
            session.commit()


def _stored(app):
    """Every address in the table, as stored."""
    with app.app_context():
        with app.container.get_db_manager().session() as session:
            return sorted(
                session.execute(text("SELECT email FROM users")).scalars().all()
            )


class TestTheCommandExists:
    """Unreachable, it fixes nothing anywhere."""

    def test_it_is_listed_among_the_maintenance_commands(self, runner, app):
        result = runner.invoke(app.cli, ["maintenance", "--help"])

        assert result.exit_code == 0
        assert "normalize-emails" in result.output

    def test_it_runs_on_an_untouched_database(self, runner, app):
        result = runner.invoke(app.cli, ["maintenance", "normalize-emails"])

        assert result.exit_code == 0, result.output
        assert "already lower case" in result.output


class TestItChangesNothingUnlessTold:
    """A report by default: this rewrites the column identity lives in."""

    def test_a_plain_run_leaves_the_rows_alone(self, runner, app):
        _store(app, "Case@Example.test")

        result = runner.invoke(app.cli, ["maintenance", "normalize-emails"])

        assert result.exit_code == 0, result.output
        assert _stored(app) == ["Case@Example.test"]

    def test_a_plain_run_says_what_it_would_do(self, runner, app):
        _store(app, "Case@Example.test")

        result = runner.invoke(app.cli, ["maintenance", "normalize-emails"])

        assert "case@example.test" in result.output
        assert "1 to change" in result.output


class TestWithApply:
    """What it lowers, and what it will not touch."""

    def test_it_lowers_an_address(self, runner, app):
        _store(app, "Case@Example.test")

        result = runner.invoke(
            app.cli, ["maintenance", "normalize-emails", "--apply"]
        )

        assert result.exit_code == 0, result.output
        assert _stored(app) == ["case@example.test"]

    def test_the_account_becomes_reachable_again(self, runner, app):
        """The point of the exercise: before it runs, this account cannot
        be found by any spelling at all.

        Reachability, not sign-in: the row is written with a fixed hash no
        password matches, so signing in could not succeed here whatever
        the lookup did.
        """
        from link_shortener.domain import Email

        _store(app, "Case@Example.test")
        runner.invoke(app.cli, ["maintenance", "normalize-emails", "--apply"])

        with app.app_context():
            with app.container.get_uow_factory()() as uow:
                assert uow.users.find_by_email(Email("Case@Example.test"))

    def test_a_clash_is_left_untouched(self, runner, app):
        """Both spellings already exist as separate accounts. Lowering one
        onto the other means choosing whose links, roles and sessions
        survive -- an owner's decision, not a maintenance command's.

        The table alone does not measure this. With the ``if not
        row["clashes"]`` filter deleted, the command attempts the write,
        the unique index refuses it, and the rows are exactly as
        untouched as they are here -- measured, this test stayed green
        with the rule it names removed. What separates the two is which
        counter moved: skipped by decision, or refused by the database
        after the command tried anyway.
        """
        _store(app, "Clash@example.test", "clash@example.test")

        result = runner.invoke(
            app.cli, ["maintenance", "normalize-emails", "--apply"]
        )

        assert result.exit_code == 0, result.output
        assert _stored(app) == ["Clash@example.test", "clash@example.test"]
        assert "left in conflict and untouched" in result.stderr
        assert "were taken by another account" not in result.stderr, (
            "the command tried the write and the index stopped it"
        )

    def test_a_clash_is_reported(self, runner, app):
        _store(app, "Clash@example.test", "clash@example.test")

        result = runner.invoke(
            app.cli, ["maintenance", "normalize-emails", "--apply"]
        )

        assert "another account also lowers to" in result.output

    def test_a_clash_does_not_stop_the_others(self, runner, app):
        """One conflict must not leave every other account stranded."""
        _store(
            app,
            "Clash@example.test",
            "clash@example.test",
            "Fine@example.test",
        )

        runner.invoke(app.cli, ["maintenance", "normalize-emails", "--apply"])

        assert "fine@example.test" in _stored(app)


class TestAPairWithNoLowerCaseMemberYet:
    """Two spellings that both need lowering collide with each other.

    The first version of this command looked for a collision by asking
    whether the lower-case spelling was *already stored*. This pair has no
    lower-case member at all, so both rows were reported safe, the update
    hit the unique index, and -- one transaction for the whole run -- every
    unrelated address stayed unmigrated while the operator had just been
    told there were no conflicts.
    """

    ADDRESSES = ("Case@Example.test", "CASE@Example.test")

    def test_both_are_reported_as_conflicting(self, runner, app):
        _store(app, *self.ADDRESSES)

        result = runner.invoke(app.cli, ["maintenance", "normalize-emails"])

        assert "2 in conflict" in result.output
        assert "0 to change" in result.output

    def test_neither_is_touched(self, runner, app):
        _store(app, *self.ADDRESSES)

        result = runner.invoke(
            app.cli, ["maintenance", "normalize-emails", "--apply"]
        )

        assert result.exit_code == 0, result.output
        assert _stored(app) == sorted(self.ADDRESSES)

    def test_an_unrelated_address_still_migrates(self, runner, app):
        """One bad pair must not strand the whole database: with every
        update in one transaction, it would."""
        _store(app, *self.ADDRESSES, "Fine@example.test")

        result = runner.invoke(
            app.cli, ["maintenance", "normalize-emails", "--apply"]
        )

        assert result.exit_code == 0, result.output
        assert "fine@example.test" in _stored(app)


class TestAnAddressOutsideAscii:
    """Where SQL ``lower()`` and ``Email.normalise`` part ways.

    The command asked SQL ``lower()`` for both halves of its work: which
    rows need lowering, and what to lower them to. On SQLite that function
    is ASCII-only by design -- ``lower('kÄthe')`` is ``'kÄthe'`` -- so
    every one of these addresses equalled its own lowered form and the
    filter does not return it. With the rule left in SQL, each address
    below is reported as "already lower case", while the repository --
    which asks ``Email.normalise`` -- logs the same row as
    unreachable on every save and named this command as the remedy.

    That is the whole failure: a warning that cannot be acted on and does
    not stop, on an account whose owner cannot sign in. PostgreSQL lowers
    these correctly, so the suite would have stayed green on the backend
    the deployment runs and broken on the one a developer runs.
    """

    @pytest.mark.parametrize(
        "stored, expected",
        [
            ("kÄthe@example.test", "käthe@example.test"),
            ("ИВАН@example.test", "иван@example.test"),
            ("Ünal@example.test", "ünal@example.test"),
        ],
    )
    def test_it_is_seen_and_lowered(self, runner, app, stored, expected):
        _store(app, stored)

        result = runner.invoke(
            app.cli, ["maintenance", "normalize-emails", "--apply"]
        )

        assert result.exit_code == 0, result.output
        assert _stored(app) == [expected]

    def test_a_plain_run_reports_it_rather_than_calling_it_clean(
        self, runner, app
    ):
        """The report is what an operator reads before passing --apply.

        Pinned apart from the write above because the two halves failed
        together and could be fixed apart: a filter that finds the row
        and an update that leaves it alone would still write nothing,
        and would now say "1 to change" while changing nothing.
        """
        _store(app, "kÄthe@example.test")

        result = runner.invoke(app.cli, ["maintenance", "normalize-emails"])

        assert "already lower case" not in result.output
        assert "1 to change" in result.output
        assert "käthe@example.test" in result.output

    def test_the_account_becomes_reachable_again(self, runner, app):
        """The remedy the repository's warning names has to be one.

        Reachability, not sign-in: the row carries a fixed hash no
        password matches.
        """
        from link_shortener.domain import Email

        _store(app, "kÄthe@example.test")
        runner.invoke(app.cli, ["maintenance", "normalize-emails", "--apply"])

        with app.app_context():
            with app.container.get_uow_factory()() as uow:
                assert uow.users.find_by_email(Email("kÄthe@example.test"))

    def test_a_clash_outside_ascii_is_still_left_alone(self, runner, app):
        """Collision detection moved to the same rule, so it has to hold
        here too -- and this pair is invisible to SQL ``lower()``, which
        would have called both rows safe."""
        _store(app, "kÄthe@example.test", "KÄTHE@example.test")

        result = runner.invoke(
            app.cli, ["maintenance", "normalize-emails", "--apply"]
        )

        assert result.exit_code == 0, result.output
        assert _stored(app) == sorted(
            ["kÄthe@example.test", "KÄTHE@example.test"]
        )
        assert "another account also lowers to" in result.output

    def test_a_row_already_normalised_outside_ascii_is_not_reported(
        self, runner, app
    ):
        """The other direction: ``Email`` writes these, and a command that
        offered to "fix" what the domain just produced would never finish
        -- it would report the same row on every run for good."""
        _store(app, "käthe@example.test")

        result = runner.invoke(app.cli, ["maintenance", "normalize-emails"])

        assert result.exit_code == 0, result.output
        assert "already lower case" in result.output


class TestAFailureToReadIsReportedLikeOne:
    """The neighbouring commands print "ERROR: ..."; this one printed a stack.

    ``db init``, ``db drop`` and ``link create`` all wrap their work and
    exit 1 with one line. This command wrapped nothing, so an unreachable
    database -- the ordinary reason a maintenance command fails -- came
    out as a traceback with the SELECT in it, which an operator can only
    read as "something broke".
    """

    @pytest.fixture
    def unreadable(self, app, db_manager):
        """Bind the application to a manager whose SELECT fails."""

        class _Unreadable:
            def session(self):
                raise RuntimeError("connection refused: no route to db")

        app.container.db_component._manager = _Unreadable()
        yield
        app.container.db_component._manager = db_manager

    def test_it_says_error_and_exits_one(self, runner, app, unreadable):
        result = runner.invoke(app.cli, ["maintenance", "normalize-emails"])

        assert result.exit_code == 1
        assert "ERROR" in result.stderr
        assert "connection refused" in result.stderr, (
            "the reason was swallowed"
        )

    def test_no_traceback_reaches_the_operator(self, runner, app, unreadable):
        """A stack trace is not a message.

        Only that: this fixture fails while the session is being opened,
        so there is no statement to leak and the SQL half of the question
        cannot fail here. That half is asked in
        ``test_a_failure_inside_the_select_does_not_print_the_select``,
        which fails inside the query instead.
        """
        result = runner.invoke(app.cli, ["maintenance", "normalize-emails"])

        assert "Traceback" not in result.output
        assert result.exception is None or isinstance(
            result.exception, SystemExit
        ), result.exception

    def test_a_failure_inside_the_select_does_not_print_the_select(
        self, runner, app, db_manager
    ):
        """The fixture above cannot see this, and that is why it is here.

        It fails when the session is opened, so the statement never
        exists. A database that dies mid-query fails *inside* the SELECT,
        and SQLAlchemy renders the statement into the message: measured,
        "[SQL: SELECT id, email FROM users ORDER BY email]" reached the
        operator while the writing path was already trimming its own.
        """
        from sqlalchemy.exc import OperationalError

        class _FailsInTheQuery:
            def session(self):
                inner = db_manager.session()

                class _Ctx:
                    def __enter__(ctx):
                        session = inner.__enter__()

                        def execute(statement, *args, **kwargs):
                            raise OperationalError(
                                "SELECT id, email FROM users ORDER BY email",
                                {},
                                Exception("server closed the connection"),
                            )

                        session.execute = execute
                        return session

                    def __exit__(ctx, *exc):
                        return inner.__exit__(*exc)

                return _Ctx()

        app.container.db_component._manager = _FailsInTheQuery()
        try:
            result = runner.invoke(app.cli, ["maintenance", "normalize-emails"])
        finally:
            app.container.db_component._manager = db_manager

        assert result.exit_code == 1
        assert "server closed the connection" in result.stderr
        assert "SELECT id, email FROM users" not in result.output, result.output
        assert "[SQL:" not in result.output, result.output

    def test_the_apply_run_is_stopped_the_same_way(
        self, runner, app, unreadable
    ):
        """``--apply`` reads first too, and had the same hole."""
        result = runner.invoke(
            app.cli, ["maintenance", "normalize-emails", "--apply"]
        )

        assert result.exit_code == 1
        assert "ERROR" in result.stderr


class TestTheExitCodeSaysWhetherTheWorkGotDone:
    """It was 0 whatever happened, which a schedule cannot act on.

    ``db check`` is deliberately non-zero "for monitoring and CI", and
    this command has the stronger claim to it: a run that refused or
    failed on every row leaves those accounts unreachable, which is the
    condition it exists to clear.
    """

    def test_a_clean_run_exits_zero(self, runner, app):
        _store(app, "Plain@Example.test")

        result = runner.invoke(
            app.cli, ["maintenance", "normalize-emails", "--apply"]
        )

        assert result.exit_code == 0, result.output

    def test_a_report_only_run_exits_zero(self, runner, app):
        """Without ``--apply`` nothing was attempted, so nothing failed."""
        _store(app, "Plain@Example.test")

        result = runner.invoke(app.cli, ["maintenance", "normalize-emails"])

        assert result.exit_code == 0, result.output

    def test_a_conflict_alone_still_exits_zero(self, runner, app):
        """A conflict is the documented outcome, not a failure to run.

        Both members need an owner's decision about which account keeps
        its links, and the command reporting one has done its whole job.
        Making this non-zero would put every schedule into permanent
        alarm over a pair nobody intends to merge.
        """
        _store(app, "Pair@Example.test", "PAIR@example.test")

        result = runner.invoke(
            app.cli, ["maintenance", "normalize-emails", "--apply"]
        )

        assert result.exit_code == 0, result.output
        assert "left in conflict" in result.stderr


class TestTheDatabaseSErrorDoesNotCarryTheRow:
    """What the database said, not what it was asked and with which values.

    SQLAlchemy renders the statement and its parameters into the message,
    and the parameters here are people's addresses. A ``DataError`` reads
    "[parameters: {'email': 'person@example.test', ...}]" -- printed to the
    terminal and into whatever log a scheduled run
    writes to. The reading path already refuses to show its SQL.
    """

    @pytest.fixture
    def failing_with_sql(self, app, db_manager):
        """Bind a manager whose writes raise a fully rendered DataError."""
        from sqlalchemy.exc import DataError

        class _Failing:
            def session(self):
                inner = db_manager.session()

                class _Ctx:
                    def __enter__(ctx):
                        session = inner.__enter__()
                        real_execute = session.execute

                        def execute(statement, *args, **kwargs):
                            if "UPDATE" in str(statement):
                                raise DataError(
                                    "UPDATE users SET email = :email "
                                    "WHERE id = :id AND email = :stored",
                                    {
                                        "email": "leak@example.test",
                                        "id": "u0",
                                        "stored": "Leak@Example.test",
                                    },
                                    Exception("value too long"),
                                )
                            return real_execute(statement, *args, **kwargs)

                        session.execute = execute
                        return session

                    def __exit__(ctx, *exc):
                        return inner.__exit__(*exc)

                return _Ctx()

        app.container.db_component._manager = _Failing()
        yield
        app.container.db_component._manager = db_manager

    def test_the_address_is_not_printed(self, runner, app, failing_with_sql):
        """Asserted on stderr as a whole, with nothing carved out of it.

        The list of addresses this command is about to change goes to
        stdout; stderr carries only the complaints. So the address has no
        business being on stderr at all, and the assertion does not have
        to know how the report line is spaced -- an earlier version cut
        the exact string "  leak@example.test -> " out of the text first,
        which would have passed just as well if the report had moved to
        the wrong stream.
        """
        _store(app, "Leak@Example.test")

        result = runner.invoke(
            app.cli, ["maintenance", "normalize-emails", "--apply"]
        )

        assert "value too long" in result.stderr, "the cause was swallowed"
        assert "parameters" not in result.stderr, result.stderr
        assert "leak@example.test" not in result.stderr, result.stderr
        assert "Leak@Example.test" not in result.stderr, result.stderr

    def test_the_statement_is_not_printed(self, runner, app, failing_with_sql):
        """The reading path refuses this, and the writing path was louder."""
        _store(app, "Leak@Example.test")

        result = runner.invoke(
            app.cli, ["maintenance", "normalize-emails", "--apply"]
        )

        assert "UPDATE users" not in result.output, result.output
        assert "[SQL:" not in result.output, result.output


