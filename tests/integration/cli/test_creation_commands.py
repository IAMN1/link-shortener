"""The commands that create an account or a link, and what they must produce.

These four paths had no test anywhere in the suite, and the gap was
measured rather than assumed: with ``is_active=is_active`` changed to
``is_active=False`` -- every account created disabled, nobody able to sign
in -- the whole suite still passed, and so it did with the role dropped,
with ``link create`` printing the original URL where the short one belongs,
and with the migration command announcing the database it was told not to
touch.

What is checked is the row rather than the wording: the wording is built
from the entity the command holds, not from what the database kept, so
without ``uow.commit()`` the command still exits 0 and still reports the
account created.
"""

import pytest
from flask.testing import FlaskCliRunner
from sqlalchemy import inspect

from link_shortener.domain.value_objects.email import Email
from link_shortener.domain.value_objects.short_code import ShortCode
from link_shortener.infrastructure.configs.app.testing import TestingConfig
from link_shortener.infrastructure.database.manager import DatabaseManager
from link_shortener.infrastructure.database.seed import seed_base_roles


class CreationConfig(TestingConfig):
    """Testing profile that seeds nothing on its own."""

    LOGGING_ENABLED = False
    AUDIT_ENABLED = False
    AUTO_SEED_ROLES = False


@pytest.fixture
def db_manager():
    """A database with the schema and the base roles in place."""
    manager = DatabaseManager(
        database_url=CreationConfig.DATABASE_URL,
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

    application = create_app(config=CreationConfig())
    application.container.db_component._manager = db_manager
    return application


@pytest.fixture
def runner(app):
    """CLI runner bound to the app."""
    return FlaskCliRunner(app)


def _every_command(group, path=()):
    """Walk a click tree, yielding the path to every command and group.

    Groups are yielded too: a group prints its own docstring for
    ``flask <group> --help``, so a walk over leaves alone would miss rst
    markup left in a group's help.

    Args:
        group: A click group or command to walk.
        path: Names collected so far, used by the recursion.

    Yields:
        ``(path, command)`` for the node and each of its descendants.
    """
    yield path, group

    for name, child in (getattr(group, "commands", None) or {}).items():
        yield from _every_command(child, path + (name,))


def _stored_user(app, address):
    """Read an account back through the repository, or None."""
    with app.app_context():
        with app.container.get_uow_factory()() as uow:
            return uow.users.find_by_email(Email(address))


class TestCreateUser:
    """``flask create-user`` must produce an account that can be used."""

    def test_the_account_it_creates_is_active(self, runner, app):
        """An account created disabled is an account nobody can sign in to.

        The flag the command prints is read off the entity it just built,
        so it is a true statement about that object and no statement at all
        about what the database kept. The row is what this asserts.
        """
        result = runner.invoke(
            app.cli,
            ["create-user", "--email", "active-check@example.test",
             "--password", "Str0ng!Passw0rd", "--role", "user"],
        )

        assert result.exit_code == 0, result.output
        stored = _stored_user(app, "active-check@example.test")
        assert stored is not None
        assert stored.is_active is True

    def test_the_account_can_be_signed_in_to_with_the_password_given(
        self, runner, app
    ):
        """The password reaching the database has to be the one typed.

        Nothing above this notices otherwise: an account stored with a
        mangled password is active, carries its role and reports itself
        created, so every other assertion here passes while the operator
        cannot sign in with what they typed.

        Asked through ``authenticate``, which is what the login route
        calls, so this is the question the operator will be asking.
        """
        address = "signin-check@example.test"
        password = "Str0ng!Passw0rd"
        result = runner.invoke(
            app.cli,
            ["create-user", "--email", address,
             "--password", password, "--role", "user"],
        )

        assert result.exit_code == 0, result.output
        with app.app_context():
            auth = app.container.get_authentication_service()
            assert auth.authenticate(address, password) is not None
            # And not because authenticate says yes to anything.
            assert auth.authenticate(address, password.lower()) is None

    def test_the_role_it_was_asked_for_is_the_role_it_assigns(self, runner, app):
        """``--role`` is the whole point of the command.

        An account created with no role at all still signs in and still
        reads as an account; what it cannot do is anything that needs a
        permission, and nothing about the account says why.
        """
        result = runner.invoke(
            app.cli,
            ["create-user", "--email", "role-check@example.test",
             "--password", "Str0ng!Passw0rd", "--role", "analyst"],
        )

        assert result.exit_code == 0, result.output
        stored = _stored_user(app, "role-check@example.test")
        assert stored is not None
        # The exact list, not membership. "analyst in roles" is the same
        # assertion with the dangerous half removed: measured, it passes
        # while the command hands out ``["analyst", "admin"]``, which is an
        # administrator created by a command asked for an analyst. Nothing
        # here grants a second role legitimately -- this is the CLI, not
        # registration, where the default role is added on purpose.
        assert [r.name for r in stored.roles] == ["analyst"]

    def test_a_role_that_does_not_exist_stops_the_command(self, runner, app):
        """Refused rather than created role-less, and said out loud."""
        result = runner.invoke(
            app.cli,
            ["create-user", "--email", "no-such-role@example.test",
             "--password", "Str0ng!Passw0rd", "--role", "nosuchrole"],
        )

        assert result.exit_code == 1
        assert "nosuchrole" in result.output
        assert _stored_user(app, "no-such-role@example.test") is None


class TestCreateAdmin:
    """``flask create-admin`` must produce an administrator, not a user."""

    def test_it_creates_an_active_account_holding_the_admin_role(
        self, runner, app
    ):
        """The role is the difference between this command and create-user.

        Without it the command is an expensive way to make an ordinary
        account, and the deployment that ran it has no administrator while
        being told it has one.
        """
        result = runner.invoke(
            app.cli,
            ["create-admin", "--email", "admin-check@example.test",
             "--password", "Str0ng!Passw0rd"],
        )

        assert result.exit_code == 0, result.output
        stored = _stored_user(app, "admin-check@example.test")
        assert stored is not None
        assert stored.is_active is True
        assert [r.name for r in stored.roles] == ["admin"]

        # This command is how a fresh deployment gets its first
        # administrator, so an account nobody can sign in to is the same as
        # no administrator at all.
        with app.app_context():
            auth = app.container.get_authentication_service()
            assert auth.authenticate(
                "admin-check@example.test", "Str0ng!Passw0rd"
            ) is not None


class TestCreateAdminRefusesAPasswordNobodyTyped:
    """A password of spaces is the one length alone cannot catch.

    Eight spaces are eight characters and cleared every bar the policy
    had: the empty-string check ahead of it is a ``if not value``, which
    a string of spaces passes, and the floor below it counts characters.
    ``str.strip()`` is Unicode-aware, so tabs and non-breaking spaces are
    caught with the plain ones. NUL has a rule of its own next door: it
    is not whitespace, and bcrypt treats it as the end of the key.
    Without the check ``create-admin`` accepts "        " and creates the
    most privileged account in the service with it, at a hidden prompt
    where nobody sees what was typed.
    """

    @pytest.mark.parametrize(
        "password", ["        ", "\t\t\t\t\t\t\t\t", "\u00a0" * 8]
    )
    def test_a_blank_password_is_refused(self, runner, app, password):
        """Tabs and the non-breaking space are the same nothing.

        ``str.strip()`` is Unicode-aware, so a value made of U+00A0 --
        what a paste out of a rendered document carries -- is caught with
        the plain spaces rather than sailing past a check written for
        ASCII.
        """
        result = runner.invoke(
            app.cli,
            ["create-admin", "--email", "blank-pass@example.test",
             "--password", password],
        )

        assert result.exit_code == 1, result.output
        assert _stored_user(app, "blank-pass@example.test") is None

    def test_spaces_inside_a_password_are_kept(self, runner, app):
        """The other half, and a rule of its own.

        NIST SP 800-63B asks that spaces be accepted inside a password
        and that verifiers not truncate, so a passphrase must survive
        exactly as typed -- including the trailing space, which still
        counts towards the length. A check that stripped before storing
        would pass the test above and quietly change what people type.
        """
        typed = " correct horse battery staple "
        result = runner.invoke(
            app.cli,
            ["create-admin", "--email", "spaced-pass@example.test",
             "--password", typed],
        )

        assert result.exit_code == 0, result.output
        with app.app_context():
            auth = app.container.get_authentication_service()
            assert auth.authenticate("spaced-pass@example.test", typed) is not None
            # Stored as typed: the stripped spelling is a different password.
            assert auth.authenticate(
                "spaced-pass@example.test", typed.strip()
            ) is None


class TestCreateAdminConfirmsAPasswordItAsksFor:
    """The neighbouring commands do, and this one creates the admin.

    ``create-user`` and ``security reset-password`` both declare
    ``confirmation_prompt=True``. This command asked once, with the input
    hidden, so a typo was invisible and uncatchable: the account is
    created, the command reports success, the password stored is not the
    one meant -- and there is no way back, because signing in needs the
    password and resetting it needs an administrator.
    """

    def test_a_mistyped_confirmation_does_not_create_the_account(
        self, runner, app
    ):
        """With nothing left on stdin, the command ends having made nothing.

        What click does on a mismatch is ask again -- it does not abort --
        so this measures the run where the operator has no more input to
        give. The case where they do is the test below; without it, the
        name of this one claims a refusal that does not happen.
        """
        result = runner.invoke(
            app.cli, ["create-admin", "--email", "typo@example.test"],
            input="Str0ng!Passw0rd\nStr0ng!Passw0rj\n",
        )

        assert result.exit_code != 0
        assert _stored_user(app, "typo@example.test") is None

    def test_the_typo_is_not_the_password_that_gets_stored(self, runner, app):
        """The mismatch is caught, the retry is what counts.

        The point of confirming is that the value stored is the one typed
        twice. Checked by signing in: the mistyped spelling must not open
        the account, the confirmed one must.
        """
        result = runner.invoke(
            app.cli, ["create-admin", "--email", "retyped@example.test"],
            input="Str0ng!Passw0rj\nStr0ng!Passw0rd\n"
                  "Str0ng!Passw0rd\nStr0ng!Passw0rd\n",
        )

        assert result.exit_code == 0, result.output
        with app.app_context():
            auth = app.container.get_authentication_service()
            assert auth.authenticate(
                "retyped@example.test", "Str0ng!Passw0rd"
            ) is not None
            assert auth.authenticate(
                "retyped@example.test", "Str0ng!Passw0rj"
            ) is None

    def test_an_empty_password_is_refused_rather_than_prompted_for(
        self, runner, app
    ):
        """``--password ""`` is a script whose variable did not get filled.

        The check asks whether a value is truthy, not whether it was
        given, so an empty one counts as missing -- which is the answer
        that keeps ``--non-interactive`` honest: a blank secret must not
        become a prompt, and must not become an account either.
        """
        result = runner.invoke(
            app.cli,
            ["create-admin", "--non-interactive",
             "--email", "blank-arg@example.test", "--password", ""],
            input="",
        )

        assert result.exit_code == 1
        assert "--password" in result.stderr
        assert _stored_user(app, "blank-arg@example.test") is None

    def test_a_password_given_on_the_command_line_is_not_asked_about(
        self, runner, app
    ):
        """A script has already said it once, and cannot say it twice.

        Confirming a ``--password`` would put the prompt back in the path
        ``--non-interactive`` exists to keep clear.
        """
        result = runner.invoke(
            app.cli,
            ["create-admin", "--non-interactive",
             "--email", "unasked@example.test",
             "--password", "Str0ng!Passw0rd"],
            input="",
        )

        assert result.exit_code == 0, result.output
        assert _stored_user(app, "unasked@example.test") is not None


class TestCreateAdminWithoutATerminal:
    """``--non-interactive`` is what a provisioning script passes.

    The flag has to be consulted before click prompts. Declared as
    prompting options, ``--email`` and ``--password`` are asked for ahead
    of the body, so with the flag set, no values and stdin closed the
    command prints "Email:" and exits 1 with ``Aborted!`` -- the failure
    the flag exists to prevent.

    Every case here supplies no input at all, which is the point: a test
    that hands the runner a string tests the prompt rather than the flag.
    """

    def test_it_refuses_a_missing_email_instead_of_asking(self, runner, app):
        result = runner.invoke(
            app.cli,
            ["create-admin", "--non-interactive",
             "--password", "Str0ng!Passw0rd"],
            input="",
        )

        assert result.exit_code == 1, result.output
        assert "--email" in result.output
        assert "Email:" not in result.output

    def test_it_refuses_a_missing_password_instead_of_asking(
        self, runner, app
    ):
        result = runner.invoke(
            app.cli,
            ["create-admin", "--non-interactive",
             "--email", "no-password@example.test"],
            input="",
        )

        assert result.exit_code == 1, result.output
        assert "--password" in result.output
        assert "Password:" not in result.output
        assert _stored_user(app, "no-password@example.test") is None

    def test_it_names_both_missing_values_at_once(self, runner, app):
        """A script fixed on the first complaint would return for the
        second, and each round trip is a failed deployment."""
        result = runner.invoke(
            app.cli, ["create-admin", "--non-interactive"], input=""
        )

        assert result.exit_code == 1, result.output
        assert "--email" in result.output
        assert "--password" in result.output
        # A refusal belongs on stderr: a provisioning script that logs
        # stdout as the command's product would otherwise file the
        # complaint as output. ``Result.output`` mixes the streams, so
        # the words alone do not measure this.
        assert "required with --non-interactive" in result.stderr
        assert result.stdout == ""

    def test_it_creates_the_account_when_both_are_given(self, runner, app):
        """The half that matters: refusing everything would pass the three
        assertions above and still leave the flag useless."""
        result = runner.invoke(
            app.cli,
            ["create-admin", "--non-interactive",
             "--email", "scripted@example.test",
             "--password", "Str0ng!Passw0rd"],
            input="",
        )

        assert result.exit_code == 0, result.output
        stored = _stored_user(app, "scripted@example.test")
        assert stored is not None
        assert [r.name for r in stored.roles] == ["admin"]

    def test_without_the_flag_it_still_asks(self, runner, app):
        """Removing the prompts would be the other way to make the flag
        true, and it would take the interactive command with it."""
        result = runner.invoke(
            app.cli, ["create-admin"],
            # The password is typed twice because the prompt confirms it.
            input="asked@example.test\nStr0ng!Passw0rd\nStr0ng!Passw0rd\n",
        )

        assert result.exit_code == 0, result.output
        assert "Email:" in result.output
        assert _stored_user(app, "asked@example.test") is not None


class TestTheOtherTwoCommandsThatTakeASecret:
    """``create-user`` and ``security reset-password``, from a script.

    Both declared ``--email`` and ``--password`` as prompting options,
    which is the shape ``create-admin`` was taken out of and the reason
    ``--non-interactive`` exists at all: a prompting option is asked for
    before the body runs, so no flag can be consulted and no branch can
    refuse. Run with stdin closed they printed ``Password:``, warned
    "Password input may be echoed", and died with ``Aborted!`` and exit
    code 1 -- the one situation the decision in ``docs/decisions.md``
    ("`--non-interactive` refuses instead of asking") was written about.

    Every case supplies no input, which is what makes it a test of the
    flag rather than of the prompt.
    """

    def test_create_user_refuses_a_missing_password_instead_of_asking(
        self, runner, app
    ):
        result = runner.invoke(
            app.cli,
            ["create-user", "--non-interactive", "--role", "user",
             "--email", "scripted-user@example.test"],
            input="",
        )

        assert result.exit_code == 1, result.output
        assert "--password" in result.output
        assert "Password:" not in result.output
        assert _stored_user(app, "scripted-user@example.test") is None

    def test_create_user_names_both_missing_values_at_once(self, runner, app):
        result = runner.invoke(
            app.cli,
            ["create-user", "--non-interactive", "--role", "user"],
            input="",
        )

        assert result.exit_code == 1, result.output
        assert "--email" in result.stderr
        assert "--password" in result.stderr
        assert result.stdout == ""

    def test_create_user_creates_the_account_when_both_are_given(
        self, runner, app
    ):
        result = runner.invoke(
            app.cli,
            ["create-user", "--non-interactive", "--role", "user",
             "--email", "provisioned@example.test",
             "--password", "Str0ng!Passw0rd"],
            input="",
        )

        assert result.exit_code == 0, result.output
        assert _stored_user(app, "provisioned@example.test") is not None

    def test_create_user_without_the_flag_still_asks(self, runner, app):
        result = runner.invoke(
            app.cli,
            ["create-user", "--role", "user"],
            input="asked-user@example.test\nStr0ng!Passw0rd\nStr0ng!Passw0rd\n",
        )

        assert result.exit_code == 0, result.output
        assert "Email:" in result.output
        assert _stored_user(app, "asked-user@example.test") is not None

    def test_reset_password_refuses_instead_of_asking(self, runner, app):
        """
        The command with the most reason to be scriptable: a password is
        reset from a runbook, at the point somebody has lost theirs.
        """
        result = runner.invoke(
            app.cli,
            ["security", "reset-password", "--non-interactive",
             "--email", "someone@example.test"],
            input="",
        )

        assert result.exit_code == 1, result.output
        assert "--password" in result.output
        assert "Password:" not in result.output

    def test_reset_password_changes_the_password_when_both_are_given(
        self, runner, app
    ):
        runner.invoke(
            app.cli,
            ["create-user", "--non-interactive", "--role", "user",
             "--email", "resets@example.test",
             "--password", "Str0ng!Passw0rd"],
            input="",
        )

        result = runner.invoke(
            app.cli,
            ["security", "reset-password", "--non-interactive",
             "--email", "resets@example.test",
             "--password", "An0ther!Passw0rd"],
            input="",
        )

        assert result.exit_code == 0, result.output
        assert "resets@example.test" in result.output

    def test_reset_password_without_the_flag_still_asks(self, runner, app):
        runner.invoke(
            app.cli,
            ["create-user", "--non-interactive", "--role", "user",
             "--email", "asked-reset@example.test",
             "--password", "Str0ng!Passw0rd"],
            input="",
        )

        result = runner.invoke(
            app.cli,
            ["security", "reset-password"],
            input="asked-reset@example.test\nAn0ther!Passw0rd\nAn0ther!Passw0rd\n",
        )

        assert result.exit_code == 0, result.output
        assert "Email:" in result.output


class TestLinkCreate:
    """``flask link create`` must report the link it made."""

    def test_it_prints_the_short_link_and_not_the_target(self, runner, app):
        """The short URL is the one thing the command exists to hand over.

        Printing the target instead is invisible in the exit code and in
        every other line: the command still succeeds, still names a code,
        and the operator copies an address that shortens nothing.
        """
        target = "https://example.test/a-page-to-shorten"
        result = runner.invoke(app.cli, ["link", "create", "--url", target])

        assert result.exit_code == 0, result.output

        codes = [
            line.split("Short code:")[1].strip()
            for line in result.output.splitlines()
            if "Short code:" in line
        ]
        assert len(codes) == 1
        code = codes[0]

        short_url_lines = [
            line for line in result.output.splitlines() if "Short URL:" in line
        ]
        assert len(short_url_lines) == 1
        short_url = short_url_lines[0].split("Short URL:")[1].strip()

        # The line has to carry the code that was just issued, and must not
        # be the target dressed up as a result.
        assert short_url.endswith(code)
        assert short_url != target
        assert target not in short_url

        with app.app_context():
            with app.container.get_uow_factory()() as uow:
                stored = uow.links.find_by_code(ShortCode(code))
        assert stored is not None
        assert stored.original_url.value == target

    def test_the_code_asked_for_is_the_code_issued(self, runner, app):
        """``--code`` is a request the command must honour or refuse.

        Silently issuing a generated code instead is invisible in the exit
        status and in every printed line, and the operator who asked for a
        branded code walks away with a random one -- usually after
        publishing the one they asked for.
        """
        result = runner.invoke(
            app.cli,
            ["link", "create", "--url", "https://example.test/branded",
             "--code", "launch2026"],
        )

        assert result.exit_code == 0, result.output
        assert "Short code: launch2026" in result.output

        with app.app_context():
            with app.container.get_uow_factory()() as uow:
                stored = uow.links.find_by_code(ShortCode("launch2026"))
        assert stored is not None
        assert stored.original_url.value == "https://example.test/branded"

    def test_the_link_it_makes_belongs_to_nobody_and_does_not_expire(
        self, runner, app
    ):
        """A link made from the command line is not a guest's link.

        The command builds a context with neither an account nor an
        address, and that is deliberate: charged to a guest instead, a CLI
        link takes a seven-day expiry nobody asked for and spends an
        allowance counted per address, so the eleventh ``link create`` on a
        host answers "Guest link limit of 10 exceeded". One extra argument
        on the context -- ``remote_addr="127.0.0.1"`` -- is enough to do it.
        """
        result = runner.invoke(
            app.cli, ["link", "create", "--url", "https://example.test/from-the-cli"]
        )
        assert result.exit_code == 0, result.output

        code = [
            line.split("Short code:")[1].strip()
            for line in result.output.splitlines()
            if "Short code:" in line
        ][0]

        with app.app_context():
            with app.container.get_uow_factory()() as uow:
                stored = uow.links.find_by_code(ShortCode(code))

        assert stored is not None
        assert stored.owner is None
        assert stored.guest_identifier is None
        assert stored.expires_at is None

    def test_it_says_when_the_link_was_not_new(self, runner, app):
        """The second call deduplicates, and the report has to show it."""
        target = "https://example.test/asked-for-twice"

        first = runner.invoke(app.cli, ["link", "create", "--url", target])
        second = runner.invoke(app.cli, ["link", "create", "--url", target])

        assert first.exit_code == 0, first.output
        assert second.exit_code == 0, second.output
        assert "Is new: True" in first.output
        assert "Is new: False" in second.output

    def test_the_headline_does_not_claim_a_link_it_did_not_make(
        self, runner, app
    ):
        """"Is new: False" four lines under "created successfully!".

        The two lines contradicted each other and only one of them is
        read: an operator shortening a URL a colleague had already
        shortened was told they had just created the link they were being
        handed. The line above is what a person skims and what a script
        greps, so it is the one that has to be true.
        """
        target = "https://example.test/shortened-by-somebody-else"

        first = runner.invoke(app.cli, ["link", "create", "--url", target])
        second = runner.invoke(app.cli, ["link", "create", "--url", target])

        assert "created successfully" in first.output, first.output
        assert "created successfully" not in second.output, second.output
        assert "already shortened" in second.output, second.output

    def test_a_custom_code_that_was_not_issued_is_not_announced_as_created(
        self, runner, app
    ):
        """The case where the wrong headline costs something.

        The URL deduplicates against the existing link, so the code
        ``--code`` asked for is not issued and the code printed is the
        older one. Told "created successfully", a script that cleans up
        after itself deletes a link it never made and somebody else is
        using.
        """
        target = "https://example.test/already-has-a-code"
        runner.invoke(
            app.cli,
            ["link", "create", "--url", target, "--code", "theirlink"],
        )

        second = runner.invoke(
            app.cli,
            ["link", "create", "--url", target, "--code", "minelink1"],
        )

        assert second.exit_code == 0, second.output
        assert "Short code: theirlink" in second.output
        assert "created successfully" not in second.output

    def test_it_says_outright_that_the_requested_code_was_not_issued(
        self, runner, app
    ):
        """The headline alone leaves the operator to notice by comparing.

        Nothing in the report named ``--code`` at all, and the exit
        status was 0. The code asked for is still free afterwards, so an
        operator who published it has published an address that resolves
        to nothing.
        """
        target = "https://example.test/code-ignored"
        runner.invoke(app.cli, ["link", "create", "--url", target])

        second = runner.invoke(
            app.cli,
            ["link", "create", "--url", target, "--code", "wantedcode"],
        )

        assert second.exit_code == 0, second.output
        assert "wantedcode" in second.output
        assert "not issued" in second.output

        # The stream, not only the words. ``Result.output`` mixes stdout
        # and stderr, so an assertion on it passes whichever stream the
        # note went to -- measured: moving the note to stdout left the
        # whole suite green while a script reading the report on stdout
        # started swallowing an extra line into its parse.
        assert "not issued" in second.stderr
        assert "not issued" not in second.stdout

        with app.app_context():
            with app.container.get_uow_factory()() as uow:
                assert uow.links.find_by_code(ShortCode("wantedcode")) is None

    def test_a_code_that_was_issued_draws_no_such_note(self, runner, app):
        """The note must not fire on the ordinary path, or it stops
        meaning anything."""
        result = runner.invoke(
            app.cli,
            ["link", "create", "--url", "https://example.test/code-honoured",
             "--code", "goodcode1"],
        )

        assert result.exit_code == 0, result.output
        assert "not issued" not in result.output

    def test_an_empty_code_is_refused_rather_than_generated(self, runner, app):
        """``--code "$CODE"`` with the variable unset is how this arrives.

        The condition guarding the note is ``if code and ...``, which is
        false for an empty string, and so is every other test of the
        option: the command generated a code, said nothing, and exited 0.
        A script that asked for a specific code then carried on with one
        it never chose -- and reserving a particular code is the only
        reason to pass the option at all.
        """
        result = runner.invoke(
            app.cli,
            ["link", "create", "--url", "https://example.test/empty-code",
             "--code", ""],
        )

        assert result.exit_code == 1
        assert "--code" in result.stderr
        assert result.stdout == "", "a link was reported as created"

    def test_a_code_of_spaces_is_refused_too(self, runner, app):
        """Same variable, quoted around a value that was only whitespace."""
        result = runner.invoke(
            app.cli,
            ["link", "create", "--url", "https://example.test/spaces-code",
             "--code", "   "],
        )

        assert result.exit_code == 1
        assert "--code" in result.stderr

    def test_nothing_is_created_by_the_refused_run(self, runner, app):
        """Refusing after creating the link would be the worse half.

        The URL must be untouched: a run that shortened it anyway leaves
        the operator's retry hitting the deduplication path, where the
        code they finally pass is ignored on purpose.
        """
        target = "https://example.test/refused-leaves-nothing"
        runner.invoke(
            app.cli, ["link", "create", "--url", target, "--code", ""]
        )

        second = runner.invoke(
            app.cli, ["link", "create", "--url", target, "--code", "wantedone"]
        )

        assert second.exit_code == 0, second.output
        assert "wantedone" in second.stdout
        assert "not issued" not in second.output

    def test_no_note_when_no_code_was_asked_for(self, runner, app):
        """Nobody asked for a code, so there is nothing to report.

        The condition has two halves and only one was held: dropping the
        "was a code asked for" half printed ``--code None was not
        issued`` on the ordinary deduplicating path, and nothing in the
        suite noticed.
        """
        target = "https://example.test/no-code-at-all"
        runner.invoke(app.cli, ["link", "create", "--url", target])

        second = runner.invoke(app.cli, ["link", "create", "--url", target])

        assert second.exit_code == 0, second.output
        assert "not issued" not in second.output
        assert "None" not in second.output
        assert second.stderr == ""

    def test_no_help_text_carries_source_markup(self, runner, app):
        """``--help`` prints the docstring, so the docstring is help.

        Named for what it measures and no more. Whether a help text
        actually describes its command is not machine-checkable -- a
        docstring replaced with a description of a different,
        destructive command passes this and should not be read as
        having been checked. What is checked is the marker that
        distinguishes a docstring written for a reader of the source
        from one written for an operator: ``rst`` markup, which click
        prints literally, double backticks and all.

        A docstring written for a reader of the source puts its markup and
        its reasoning in front of every operator who asks what the command
        does.

        Every command is walked rather than the two that were fixed:
        checking only those would leave the rule enforced where it had
        just been applied and nowhere else, which is how the other three
        got there.
        """
        offenders = []
        for path, command in _every_command(app.cli):
            result = runner.invoke(app.cli, list(path) + ["--help"])

            assert result.exit_code == 0, (path, result.output)
            if "``" in result.output:
                offenders.append(" ".join(path))
            if not (command.__doc__ or "").strip():
                offenders.append(f"{' '.join(path)} (no help at all)")

        assert offenders == [], offenders


class TestMigrateWithoutAlembic:
    """``flask db migrate`` with Alembic off must not name the database."""

    def test_it_neither_migrates_nor_announces_the_database(self, runner, app):
        """It must leave the schema alone, and say nothing about where it is.

        Both halves are asserted because the wording alone is no evidence
        of the deed: measured, a ``drop_all`` added to this branch took
        every table with it while the command still exited 0 and still
        printed "Alembic is disabled", and the text-only version of this
        test stayed green.

        Announcing the database is the smaller half, and not free either:
        the URL carries the host and the user, and this branch has no
        reason to put a connection string into a deployment log.
        ``TestingConfig`` runs with ``USE_ALEMBIC`` off, which is exactly
        the branch under test.
        """
        assert app.config.get("USE_ALEMBIC") is False

        with app.app_context():
            engine = app.container.get_db_manager().engine
            before = set(inspect(engine).get_table_names())
        assert "users" in before, "the fixture is supposed to have a schema"

        result = runner.invoke(app.cli, ["db", "migrate"])

        assert result.exit_code == 0, result.output
        assert "Alembic is disabled" in result.output
        assert "sqlite" not in result.output.lower()
        assert "Database:" not in result.output

        with app.app_context():
            after = set(inspect(app.container.get_db_manager().engine).get_table_names())
        assert after == before


class TestTheAlembicGroupWithAlembicOff:
    """The refusal that stands between the two ways of building a schema.

    ``USE_ALEMBIC`` picks one: ``flask db init`` creates the tables
    straight from the models and writes no revision, and a database built
    that way then migrated tries to create tables that already exist.
    ``db init``, ``db drop`` and ``db migrate`` have always honoured the
    flag; the ``alembic`` group did not until it gained
    ``_require_alembic_enabled``.

    That refusal had no test of any kind. The cause is general and worth
    naming here: click 8.2 merged the streams into ``Result.output``, so
    ``"..." in result.output`` passes whichever stream carried the text,
    and an assertion written that way cannot tell a refusal on stderr
    from one printed to stdout. click 8.3 restored ``result.stderr`` and
    ``result.stdout``, and these use them.
    """

    @pytest.mark.parametrize(
        "command",
        [
            ["alembic", "upgrade"],
            ["alembic", "downgrade"],
            # ``migrate`` takes a required message argument; without one
            # click refuses first, with exit code 2, and the refusal
            # under test is never reached.
            ["alembic", "migrate", "a message"],
        ],
    )
    def test_the_command_is_refused(self, runner, app, command):
        """Every schema-changing command in the group, not just one."""
        assert app.config.get("USE_ALEMBIC") is False

        result = runner.invoke(app.cli, command)

        assert result.exit_code == 1, result.output
        assert "USE_ALEMBIC is disabled" in result.stderr

    def test_the_refusal_names_the_way_that_does_work(self, runner, app):
        """A refusal with no remedy sends the operator to the source.

        The two commands named here are the ones that manage a schema
        while the flag is off, so the message has to survive intact.
        """
        result = runner.invoke(app.cli, ["alembic", "upgrade"])

        assert "flask db init" in result.stderr
        assert "flask db drop" in result.stderr

    def test_the_refusal_goes_to_stderr_and_not_to_stdout(self, runner, app):
        """The stream is the half no earlier assertion could see.

        A refusal on stdout is filed as the command's product by any
        script that logs the two separately -- and this branch prints
        nothing else, so stdout must be empty.
        """
        result = runner.invoke(app.cli, ["alembic", "upgrade"])

        assert "USE_ALEMBIC is disabled" not in result.stdout
        assert result.stdout == "", result.stdout

    def test_the_database_is_not_named(self, runner, app):
        """``_echo_target`` prints the URL, and it must not be reached.

        The refusal happens before that line: a connection string carries
        the host and the user, and a command that refused to do anything
        has no reason to put one in a deployment log.
        """
        result = runner.invoke(app.cli, ["alembic", "upgrade"])

        assert "Database:" not in result.output
        assert "sqlite" not in result.output.lower()

    def test_the_schema_is_left_alone(self, runner, app):
        """The wording is no evidence of the deed.

        A ``drop_all`` on the neighbouring branch takes every table while
        the command still prints its refusal and exits as expected.
        """
        with app.app_context():
            engine = app.container.get_db_manager().engine
            before = set(inspect(engine).get_table_names())
        assert "users" in before, "the fixture is supposed to have a schema"

        runner.invoke(app.cli, ["alembic", "upgrade"])

        with app.app_context():
            after = set(
                inspect(app.container.get_db_manager().engine).get_table_names()
            )
        assert after == before
