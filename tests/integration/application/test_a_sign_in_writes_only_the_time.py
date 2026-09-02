"""A sign-in must not put back the account as it was before the password check.

``LoginUseCase`` reads the account to check the password and then writes
``last_login``. Between those two lies a bcrypt comparison -- ~160 ms --
and the write used to be ``users.save(user)``, which writes every column
the entity carries: the address, the hash, the active flag, the confirmed
flag, and the whole role list. All of them as they were read *before* the
comparison.

So anything an administrator did to the account in that window was
silently undone by the sign-in that was already in flight. Two of the
columns are the ones an administrator is most likely to be changing at
exactly that moment, because both are what you do about an account you
believe is compromised:

  - the account was switched off, and came back on;
  - the password was changed, and the old hash was written back -- so the
    new password stopped working and the one the change was made against
    went on working.

Neither is visible from outside a race. Both are closed by writing one
column with a conditional update, which is the rule
``JwtAuthenticationService.revoke_refresh_token`` already states for
sessions and this path did not follow.

The window is opened here by wrapping ``authenticate``: the administrator
acts after the account has been read and before the sign-in writes, which
is where a real one would land. Everything else is the real use case, the
real repository and a real database.
"""

import itertools

import pytest

from link_shortener.application.context import RequestContext


PASSWORD = "Str0ng!Passw0rd"
REPLACEMENT = "Br4ndNew!Passphrase"

_addresses = itertools.count(1)
"""Its own address per test.

The ``app`` fixture builds the application once and its database outlives
every test in the session, so an address shared between two of them makes
the second one measure what the first left behind."""


def context():
    """A request context with nothing in it but an id."""
    return RequestContext(request_id="sign-in-race")


@pytest.fixture
def account(app):
    """A confirmed account of this test's own, and what acts on it.

    Returns:
        Tuple of (container, address, user id).
    """
    container = app.container
    email = f"signin-race-{next(_addresses)}@example.test"
    with container.get_uow_factory()() as uow:
        user = container.get_user_management_service().create_user(
            uow, email, PASSWORD
        )
        uow.commit()
        return container, email, user.id


def sign_in_while(container, email, meddle):
    """
    Run a sign-in with something else happening inside its window.

    Args:
        container: The application container.
        email: The account signing in.
        meddle: Called after the account has been read and before the
            sign-in writes -- which is where a concurrent administrative
            change lands.
    """
    authentication = container.get_authentication_service()
    original = authentication.authenticate

    def authenticate_then_meddle(address, password):
        found = original(address, password)
        meddle()
        return found

    authentication.authenticate = authenticate_then_meddle
    try:
        container.get_login_use_case().execute(email, PASSWORD, context())
    finally:
        authentication.authenticate = original


class TestWhatASignInMayWrite:

    def test_it_does_not_reactivate_an_account_switched_off_meanwhile(
        self, account
    ):
        container, email, user_id = account

        def deactivate():
            with container.get_uow_factory()() as uow:
                container.get_user_management_service().deactivate_user(
                    uow, user_id
                )
                uow.commit()

        sign_in_while(container, email, deactivate)

        with container.get_uow_factory()(read_only=True) as uow:
            assert uow.users.find_by_id(user_id).is_active is False, (
                "the sign-in put the account back as it was before the "
                "password was checked"
            )

    def test_it_does_not_restore_a_password_replaced_meanwhile(self, account):
        container, email, user_id = account
        users = container.get_user_management_service()

        def replace_the_password():
            with container.get_uow_factory()() as uow:
                users.update_password(
                    uow, uow.users.find_by_id(user_id), REPLACEMENT
                )
                uow.commit()

        sign_in_while(container, email, replace_the_password)

        authentication = container.get_authentication_service()
        assert authentication.authenticate(email, REPLACEMENT) is not None, (
            "the new password does not work: the sign-in wrote the old "
            "hash back over it"
        )
        assert authentication.authenticate(email, PASSWORD) is None, (
            "the password the change was made against still works"
        )

    def test_it_does_not_undo_a_role_change_made_meanwhile(self, account):
        container, email, user_id = account

        # ``analyst`` rather than ``admin``, deliberately. The ``app``
        # fixture's database outlives every test in the session, so an
        # account left holding ``admin`` here is a second administrator
        # for everything that runs afterwards -- and the checks that the
        # last administrator cannot be deleted, deactivated or demoted
        # all rest on there being exactly one. Measured: they failed
        # together, and passed one at a time.
        def make_them_an_analyst():
            with container.get_uow_factory()() as uow:
                analyst = uow.roles.get_by_name("analyst")
                container.get_user_management_service().update_roles(
                    uow, user_id, [analyst]
                )
                uow.commit()

        sign_in_while(container, email, make_them_an_analyst)

        with container.get_uow_factory()(read_only=True) as uow:
            names = {role.name for role in uow.users.find_by_id(user_id).roles}

        assert names == {"analyst"}, (
            f"the sign-in wrote the earlier role list back: {sorted(names)}"
        )

    def test_the_time_it_came_for_is_still_written(self, account):
        """The whole point of the write, and the part that must survive."""
        container, email, user_id = account

        with container.get_uow_factory()(read_only=True) as uow:
            assert uow.users.find_by_id(user_id).last_login is None

        sign_in_while(container, email, lambda: None)

        with container.get_uow_factory()(read_only=True) as uow:
            assert uow.users.find_by_id(user_id).last_login is not None
