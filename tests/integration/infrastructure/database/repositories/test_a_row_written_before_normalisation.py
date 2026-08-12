"""What happens to an address the database holds in mixed case.

``Email`` lowers what it holds on the way in and on the way out, so an
account written before normalisation comes back from the repository in
lower case -- and copying that back into the row rewrote it. Two things
followed, and both were measured on a real confirmation.

Alone, the row quietly became lower case on the first save by whichever
request happened to touch the account, outside
``flask maintenance normalize-emails`` and outside the log.

Paired with an account that already holds the lowered address, the same
write hit the unique index: confirming the address answered 500, the
token stayed unspent, and the next attempt failed identically, so the
account could never be confirmed at all. Deactivating it as an
administrator failed the same way. Merging two such accounts is nobody's
job here -- it decides whose links, roles and sessions survive -- so the
row is left exactly as it is and reported instead.
"""

import pytest
from sqlalchemy import text

from link_shortener.domain import Email, PasswordHash, User
from link_shortener.infrastructure.database.repositories.sqlalchemy_user_repository import (
    SQLAlchemyUserRepository,
)
from link_shortener.infrastructure.database.unit_of_work import (
    SQLAlchemyUnitOfWork,
)


HASH = "$2b$12$" + "x" * 53


class RecordingLogger:
    """Collects what the repository reports, in the shape a Logger takes."""

    def __init__(self):
        self.warnings = []

    def warning(self, message, **fields):
        self.warnings.append((message, fields))

    def info(self, message, **fields):
        pass

    def debug(self, message, **fields):
        pass

    def error(self, message, **fields):
        pass

    def critical(self, message, **fields):
        pass


@pytest.fixture()
def lowered(request):
    """The address as normalisation would write it.

    Unique per test: the application fixture is session-scoped, so one
    database serves the whole run and a constant address belongs to
    whichever test registered it first.
    """
    return f"mixed-{request.node.name}@example.test".lower()


@pytest.fixture()
def session(app):
    """A session on the integration database."""
    with app.app_context():
        with app.container.get_db_manager().session() as session:
            yield session


@pytest.fixture()
def mixed_case_row(session, lowered):
    """One account whose stored address is not in lower case.

    Written through SQL on purpose: the repository lowers on the way in
    as well, so a row like this cannot be created through it at all.

    Returns:
        Tuple of the account id and the address as stored.
    """
    stored = lowered.replace("mixed-", "Mixed-", 1)
    user = User.create(email=Email(lowered), password_hash=PasswordHash(HASH))
    repository = SQLAlchemyUserRepository(session)
    saved = repository.save(user)
    session.commit()

    session.execute(
        text("UPDATE users SET email = :stored WHERE id = :id"),
        {"stored": stored, "id": saved.id},
    )
    session.commit()
    return saved.id, stored


def stored_address(session, user_id):
    """Read the address exactly as the database holds it."""
    return session.execute(
        text("SELECT email FROM users WHERE id = :id"), {"id": user_id}
    ).scalar_one()


class TestTheRowIsLeftAsItIs:
    """Saving an account must not rewrite the address it was read with."""

    def test_a_save_does_not_lower_the_stored_address(
        self, session, mixed_case_row
    ):
        user_id, stored = mixed_case_row
        repository = SQLAlchemyUserRepository(session)

        user = repository.find_by_id(user_id)
        repository.save(user)
        session.commit()

        assert stored_address(session, user_id) == stored

    def test_the_entity_reads_the_row_as_it_is_written(
        self, session, mixed_case_row
    ):
        """Reconstruction is not an input, so it does not lower.

        This is what keeps the save above harmless: the entity holds the
        stored spelling, so writing it back changes nothing. Lowering
        here instead is exactly the second normalisation that turned
        every save into a rewrite.
        """
        user_id, stored = mixed_case_row
        repository = SQLAlchemyUserRepository(session)

        assert repository.find_by_id(user_id).email.value == stored

    def test_an_address_typed_by_somebody_is_still_lowered(self, lowered):
        """The way in keeps normalising, which is the whole rule.

        Pinned beside its exception so the two cannot drift: what a
        person types is lowered, what a row holds is not.
        """
        assert Email(lowered.upper()).value == lowered


    def test_an_address_that_really_changed_is_written(
        self, session, mixed_case_row, lowered
    ):
        """Preserving case must not turn into preserving everything.

        Nothing changes a stored address today -- the domain has no way
        to -- so the guard could be narrowed to "never touch an existing
        row" and no test would notice. Pinned here because the day an
        address becomes changeable, the failure would be silent: the new
        address accepted everywhere and the old one still in the column.
        """
        user_id, _ = mixed_case_row
        repository = SQLAlchemyUserRepository(session)
        elsewhere = lowered.replace("mixed-", "moved-", 1)

        user = repository.find_by_id(user_id)
        user.email = Email(elsewhere)
        repository.save(user)
        session.commit()

        assert stored_address(session, user_id) == elsewhere


class TestTheRowIsReported:
    """Silence was the other half of the defect."""

    def test_saving_it_warns_and_names_the_command(
        self, session, mixed_case_row
    ):
        user_id, stored = mixed_case_row
        logger = RecordingLogger()
        repository = SQLAlchemyUserRepository(session, logger)

        repository.save(repository.find_by_id(user_id))
        session.commit()

        assert len(logger.warnings) == 1
        _, fields = logger.warnings[0]
        assert fields["stored_email"] == stored
        assert fields["remedy"] == "flask maintenance normalize-emails"

    def test_an_ordinary_account_is_not_reported(self, session, lowered):
        """The warning has to mean something when it appears."""
        logger = RecordingLogger()
        repository = SQLAlchemyUserRepository(session, logger)

        saved = repository.save(
            User.create(
                email=Email(lowered), password_hash=PasswordHash(HASH)
            )
        )
        repository.save(repository.find_by_id(saved.id))
        session.commit()

        assert logger.warnings == []

    def test_a_repository_without_a_logger_still_saves(
        self, session, mixed_case_row
    ):
        """Nobody to report to is not a reason to fail.

        A repository built by hand -- a script, a test -- gets no logger,
        and the save has to work regardless.
        """
        user_id, stored = mixed_case_row
        repository = SQLAlchemyUserRepository(session)

        repository.save(repository.find_by_id(user_id))
        session.commit()

        assert stored_address(session, user_id) == stored


class TestTheWarningReachesTheApplicationLog:
    """The wiring, and not only what the repository does when handed one.

    The repository is built by the unit of work, which is built by the
    container. Either handover can be dropped without a single failing
    assertion about the repository itself -- measured: removing the
    logger from the unit of work left the whole suite green while the
    warning stopped being written anywhere.
    """

    def test_a_unit_of_work_hands_its_logger_to_the_repository(
        self, app, mixed_case_row
    ):
        user_id, stored = mixed_case_row
        logger = RecordingLogger()

        with app.app_context():
            uow = SQLAlchemyUnitOfWork(
                app.container.get_db_manager(), logger=logger
            )
            with uow:
                uow.users.save(uow.users.find_by_id(user_id))
                uow.commit()

        assert [f["stored_email"] for _, f in logger.warnings] == [stored]

    def test_the_container_builds_one_with_a_logger(self, app):
        """Nothing reports anything if the container stops passing it."""
        with app.app_context():
            uow = app.container.get_uow_factory()()

            assert uow.logger is not None


class TestThePairThatUsedToAnswer500:
    """Two rows that collide once lowered, which is the costly case."""

    @pytest.fixture()
    def colliding_pair(self, session, mixed_case_row, lowered):
        """The mixed-case row, plus an account holding the lowered form.

        Returns:
            The id of the account whose address is stored in mixed case.
        """
        user_id, _ = mixed_case_row
        repository = SQLAlchemyUserRepository(session)
        repository.save(
            User.create(
                email=Email(lowered), password_hash=PasswordHash(HASH)
            )
        )
        session.commit()
        return user_id

    def test_saving_the_mixed_case_account_does_not_raise(
        self, session, colliding_pair
    ):
        """This raised IntegrityError, which reached the caller as 500."""
        repository = SQLAlchemyUserRepository(session)

        repository.save(repository.find_by_id(colliding_pair))
        session.commit()

    def test_confirming_it_now_sticks(self, session, colliding_pair):
        """The state change that used to be lost with the 500.

        Confirmation is the path this was measured on: the flag was set
        on the entity, the write failed on the unique index, and the
        token was never spent -- so the same failure repeated for good.
        """
        repository = SQLAlchemyUserRepository(session)

        user = repository.find_by_id(colliding_pair)
        user.confirm_email()
        repository.save(user)
        session.commit()

        assert repository.find_by_id(colliding_pair).email_verified is True

    def test_both_rows_survive_untouched(
        self, session, colliding_pair, lowered
    ):
        """Neither account is merged, renamed or lost by the save."""
        repository = SQLAlchemyUserRepository(session)
        repository.save(repository.find_by_id(colliding_pair))
        session.commit()

        addresses = session.execute(
            text("SELECT email FROM users WHERE lower(email) = :lowered"),
            {"lowered": lowered},
        ).scalars().all()

        assert sorted(addresses) == sorted(
            [lowered, lowered.replace("mixed-", "Mixed-", 1)]
        )
