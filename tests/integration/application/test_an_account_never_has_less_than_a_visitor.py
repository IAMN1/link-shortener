"""
An account with no roles held *less* than somebody who never signed in.

An anonymous caller is answered as ``guest``, which may shorten a link. An
account carrying no roles is answered as itself, and itself grants nothing
-- so signing in took away a right rather than adding one, and nothing said
so. Measured before the refusal below existed::

    update_roles(user, [])            -> accepted, 0 roles left
    is_allowed(None, "link:create")   -> True
    is_allowed(that account, ...)     -> False

The account could not be told apart from a working one until it tried
something. It reached that state through the ordinary door: deleting a role
takes it off every wearer at once, and the wearers left bare were left bare.

Two things close it and they are different sizes. Deleting a role puts its
wearers back on the default role, which is a policy and belongs in that use
case; this file holds the other one -- the invariant. An account keeps at
least one role, refused at the service every path goes through, so no new
path can produce the state again. Parking an account is what
``deactivate_user`` is for: it says what it does, and it can be undone.
"""

import itertools

import pytest

from link_shortener.domain import ValidationError


_addresses = itertools.count()


@pytest.fixture
def account(app):
    """An ordinary account, wearing the role registration grants.

    A fresh address each time: the application is one session-wide fixture
    here, so a fixed address is registered once and refused for every test
    after the first -- which is an error, not a red assertion, and reads
    as this file being broken rather than as it sharing a database.
    """
    with app.app_context():
        uow_factory = app.container.get_uow_factory()
        service = app.container.get_user_management_service()
        with uow_factory() as uow:
            role = uow.roles.get_by_name("user")
            user = service.create_user(
                uow,
                email=f"never-bare-{next(_addresses)}@example.test",
                password="a-password-of-their-own",
                roles=[role],
            )
            uow.commit()
            return user.id


class TestTheServiceRefusesToStripTheLastRole:

    def test_an_empty_set_is_refused(self, app, account):
        with app.app_context():
            uow_factory = app.container.get_uow_factory()
            service = app.container.get_user_management_service()

            with uow_factory() as uow:
                with pytest.raises(ValidationError) as refusal:
                    service.update_roles(uow, account, [])

            assert "role" in str(refusal.value).lower()

    def test_the_account_still_wears_what_it_wore(self, app, account):
        """A refusal that changed the account would be the fault, renamed."""
        with app.app_context():
            uow_factory = app.container.get_uow_factory()
            service = app.container.get_user_management_service()

            with uow_factory() as uow:
                with pytest.raises(ValidationError):
                    service.update_roles(uow, account, [])

            with uow_factory() as uow:
                assert [r.name for r in uow.users.find_by_id(account).roles] == [
                    "user"
                ]

    def test_replacing_the_roles_still_works(self, app, account):
        """
        The half that keeps the refusal from being a wall.

        What an administrator does through this door is swap one set for
        another, and that is untouched.
        """
        with app.app_context():
            uow_factory = app.container.get_uow_factory()
            service = app.container.get_user_management_service()

            with uow_factory() as uow:
                analyst = uow.roles.get_by_name("analyst")
                service.update_roles(uow, account, [analyst])
                uow.commit()

            with uow_factory() as uow:
                assert [r.name for r in uow.users.find_by_id(account).roles] == [
                    "analyst"
                ]


class TestSigningInNeverCostsARight:

    def test_an_account_is_answered_at_least_what_a_visitor_is(
        self, app, account
    ):
        """
        The property, held whichever way the service chooses to hold it.

        This asks for the roles to be taken away and does not mind which
        answer it gets: refused, and the account keeps what it had;
        allowed, and something else has to keep it above a visitor. What
        it minds is the state afterwards -- every permission an anonymous
        caller holds, this account holds too.

        Written this way because the fault is not "an empty list was
        accepted". It is "signing in cost a right", and a later change
        that closes the empty list somewhere else, or opens it again
        under a floor in the authorization service, is still held here.
        """
        with app.app_context():
            authorization = app.container.get_authorization_service()
            uow_factory = app.container.get_uow_factory()
            service = app.container.get_user_management_service()

            with uow_factory() as uow:
                try:
                    service.update_roles(uow, account, [])
                    uow.commit()
                except ValidationError:
                    pass

            with uow_factory() as uow:
                user = uow.users.find_by_id(account)

            anonymous_may = [
                permission
                for permission in ("link:create", "link:read", "stats:view")
                if authorization.is_allowed(None, permission)
            ]

            assert anonymous_may, "a visitor may do nothing at all"
            withheld = [
                permission for permission in anonymous_may
                if not authorization.is_allowed(user, permission)
            ]

            assert withheld == [], withheld
