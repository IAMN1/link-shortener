"""A write that loses a race answers as the situation it lost to.

Every uniqueness check in this service reads first and writes second, and
the reading goes stale the moment another transaction commits. The unique
index is the only authority. ``SQLAlchemyLinkRepository`` already said so
for ``short_code``; the two indexes beside it did not, so a request that
was merely late came back as the service's own failure.

Measured against the running stack:

* six simultaneous ``POST /api/v1/admin/roles`` for one name --
  ``201, 409, 409, 500, 500, 500``;
* five simultaneous ``POST /api/v1/auth/register`` for one address --
  ``202, 500, 500`` and two throttled.

The registration case is the worse of the two: it is a public endpoint,
and the 202 is worded precisely so that a caller cannot tell whether the
address was already taken. A 500 beside it tells them.
"""

import pytest
from sqlalchemy.exc import IntegrityError

from link_shortener.domain import (
    Email, PasswordHash, Role, RoleAlreadyExistsError, User, ValidationError
)
from link_shortener.infrastructure.database.models.role_model import RoleModel
from link_shortener.infrastructure.database.models.user_model import UserModel
from link_shortener.infrastructure.database.repositories.sqlalchemy_role_repository import (
    SQLAlchemyRoleRepository,
)
from link_shortener.infrastructure.database.repositories.sqlalchemy_user_repository import (
    SQLAlchemyUserRepository,
)


HASH = "$2b$12$" + "a" * 53


@pytest.fixture()
def session(app):
    """A session of its own, rolled back after each test."""
    with app.app_context():
        db_manager = app.container.get_db_manager()
        with db_manager.session() as opened:
            yield opened
            opened.rollback()


class TestARoleNameTakenBetweenTheReadAndTheWrite:
    """The name is answered as a conflict, not as a driver error."""

    def test_the_collision_is_a_domain_refusal(self, session):
        session.add(RoleModel(id="race-held", name="race-name"))
        session.flush()
        repository = SQLAlchemyRoleRepository(session)

        # A different row, the same name: what the loser of the race holds.
        with pytest.raises(RoleAlreadyExistsError) as refusal:
            repository.save(Role(id="race-late", name="race-name"))

        assert refusal.value.role_name == "race-name"

    def test_it_is_not_the_raw_driver_error(self, session):
        """The distinction that decides 409 against 500."""
        session.add(RoleModel(id="race-held-2", name="race-name-2"))
        session.flush()
        repository = SQLAlchemyRoleRepository(session)

        try:
            repository.save(Role(id="race-late-2", name="race-name-2"))
        except IntegrityError:  # pragma: no cover - the defect, if it returns
            pytest.fail("the driver error reached the caller, which is a 500")
        except RoleAlreadyExistsError:
            pass


class TestAnAddressTakenBetweenTheReadAndTheWrite:
    """The address is answered the way the read-first check answers it."""

    def _user(self, identifier, address):
        return User(
            id=identifier,
            email=Email(address),
            password_hash=PasswordHash(HASH),
            roles=[],
        )

    def test_the_collision_is_a_domain_refusal(self, session):
        session.add(UserModel(
            id="race-user-held",
            email="race-address@example.test",
            password_hash=HASH,
            is_active=True,
        ))
        session.flush()
        repository = SQLAlchemyUserRepository(session)

        with pytest.raises(ValidationError) as refusal:
            repository.save(
                self._user("race-user-late", "race-address@example.test")
            )

        assert refusal.value.field == "email"

    def test_it_carries_the_same_sentence_as_the_read_first_check(
        self, session
    ):
        """One fact, one sentence: the catalogue holds a single msgid."""
        session.add(UserModel(
            id="race-user-held-2",
            email="race-address-2@example.test",
            password_hash=HASH,
            is_active=True,
        ))
        session.flush()
        repository = SQLAlchemyUserRepository(session)

        with pytest.raises(ValidationError) as refusal:
            repository.save(
                self._user("race-user-late-2", "race-address-2@example.test")
            )

        assert refusal.value.message == "Email already registered"


class TestWhatRegistrationDoesWithALostRace:
    """It answers exactly as it answers a taken address: 202, and a notice.

    The race is modelled rather than run: ``find_by_email`` is made to
    miss a row that is really there, which is what a concurrent commit
    looks like from inside the losing transaction. Running it for real
    needs the throttle switched off, and the throttle is the thing that
    made the fifth simultaneous registration a 429 rather than a 500.
    """

    @pytest.fixture()
    def registered(self, app, client):
        """An address that is already taken."""
        address = "already-there@example.test"
        client.post(
            "/api/v1/auth/register",
            json={"email": address, "password": "Str0ng!Passw0rd"},
        )
        return address

    def test_it_answers_the_way_a_taken_address_answers(
        self, app, client, monkeypatch, registered
    ):
        monkeypatch.setattr(
            SQLAlchemyUserRepository, "find_by_email", lambda self, email: None
        )

        answer = client.post(
            "/api/v1/auth/register",
            json={"email": registered, "password": "An0ther!Passw0rd"},
        )

        assert answer.status_code == 202, answer.get_json()

    def test_no_second_account_is_created(
        self, app, client, monkeypatch, registered
    ):
        monkeypatch.setattr(
            SQLAlchemyUserRepository, "find_by_email", lambda self, email: None
        )
        client.post(
            "/api/v1/auth/register",
            json={"email": registered, "password": "An0ther!Passw0rd"},
        )

        with app.app_context():
            db_manager = app.container.get_db_manager()
            with db_manager.session() as opened:
                held = opened.query(UserModel).filter_by(
                    email=registered
                ).count()

        assert held == 1
