"""
Tests that a link write reports the constraint that actually refused it.

`save` used to answer every integrity violation with `LinkConflictError`,
which the creation reads as "somebody took that code". Measured on the
running stack against PostgreSQL, saving a link whose owning account had
gone answered

    ForeignKeyViolation: insert or update on table "urls" violates
    foreign key constraint "fk_urls_owner_id_users"

and reached `CreateShortLinkUseCase` as a lost race: five retries, five
`Lost a race for a short code` lines, and a `CodeGenerationError` saying
"every attempt lost a race with a concurrent creation" -- for a failure
no further attempt could have got past.

Both databases are covered, because they say it differently: PostgreSQL
names the constraint and offers it as `diag.constraint_name`, SQLite
names the column in the message and offers no diagnostics. The SQLite
side is provoked for real -- foreign keys are enforced there now -- and
the PostgreSQL side is written out in the shape psycopg gives, the way
the account repository's own race test does it.
"""

import pytest
from sqlalchemy.exc import IntegrityError

from link_shortener.domain.entities.link import Link
from link_shortener.domain.exceptions import LinkConflictError
from link_shortener.domain.value_objects.original_url import OriginalUrl
from link_shortener.domain.value_objects.owner_id import OwnerID
from link_shortener.domain.value_objects.short_code import ShortCode
from link_shortener.domain.value_objects.url_hash import UrlHash
from link_shortener.infrastructure.database.repositories.sqlalchemy_link_repository import (
    SHORT_CODE_INDEX_NAME, SQLAlchemyLinkRepository,
)
from tests.integration.conftest import ensure_user


ABSENT_OWNER = "00000000-0000-0000-0000-0000000000ff"


@pytest.fixture()
def repo(app):
    """A link repository bound to the suite's database."""
    with app.app_context():
        db_manager = app.container.get_db_manager()
        with db_manager.session() as session:
            yield SQLAlchemyLinkRepository(session)


def a_link(code, tail, owner=None):
    """A link with a hash of its own, so only the code can collide."""
    return Link.create(
        url_hash=UrlHash("b" * 60 + tail),
        short_code=ShortCode(code),
        original_url=OriginalUrl(f"https://example.test/{tail}"),
        owner=OwnerID(owner) if owner else None,
    )


class Diagnostics:
    """The one field the repository reads, in the shape psycopg gives."""

    def __init__(self, constraint_name):
        self.constraint_name = constraint_name


class Refusal(Exception):
    """A driver error carrying diagnostics, as psycopg's does."""

    def __init__(self, constraint_name, message):
        super().__init__(message)
        self.diag = Diagnostics(constraint_name)


def a_violation_of(constraint_name, message):
    """An integrity error shaped like the one PostgreSQL raises."""
    return IntegrityError(
        "INSERT INTO urls", {}, Refusal(constraint_name, message)
    )


def flushing_raises(session, error):
    """Make the next flush fail the way a losing write does."""
    original = session.flush

    def flush(*args, **kwargs):
        raise error

    session.flush = flush
    return original


class TestWhatSQLiteRefuses:
    """Provoked against the real database the suite runs on."""

    def test_a_taken_code_is_a_conflict(self, repo):
        repo.save(a_link("dupe01", "0001"))
        repo.session.commit()

        try:
            with pytest.raises(LinkConflictError):
                repo.save(a_link("dupe01", "0002"))
        finally:
            repo.session.rollback()

    def test_an_owner_that_is_not_there_is_not_a_conflict(self, repo):
        """The measured race, and the reason the catch was narrowed.

        Answered as a conflict, this sends the creation round a retry
        loop that cannot succeed -- the code was never the problem.
        """
        try:
            with pytest.raises(IntegrityError):
                repo.save(a_link("gone01", "0003", owner=ABSENT_OWNER))
        finally:
            repo.session.rollback()

    def test_an_owner_that_is_there_is_saved(self, repo):
        """The other half: the guard refuses only what is missing."""
        ensure_user(repo.session, ABSENT_OWNER.replace("ff", "ee"))
        saved = repo.save(
            a_link("here01", "0004", owner=ABSENT_OWNER.replace("ff", "ee"))
        )
        repo.session.commit()

        assert repo.find_by_code(saved.short_code) is not None


class TestWhatPostgreSQLNames:
    """The same two answers, decided by the constraint psycopg names."""

    def test_the_short_code_index_is_a_conflict(self, repo):
        original = flushing_raises(repo.session, a_violation_of(
            SHORT_CODE_INDEX_NAME,
            "duplicate key value violates unique constraint "
            f'"{SHORT_CODE_INDEX_NAME}"',
        ))
        try:
            with pytest.raises(LinkConflictError):
                repo.save(a_link("pgdup1", "0005"))
        finally:
            repo.session.flush = original
            repo.session.rollback()

    def test_any_other_constraint_leaves_as_it_came(self, repo):
        original = flushing_raises(repo.session, a_violation_of(
            "fk_urls_owner_id_users",
            'insert or update on table "urls" violates foreign key '
            'constraint "fk_urls_owner_id_users"',
        ))
        try:
            with pytest.raises(IntegrityError):
                repo.save(a_link("pgfk01", "0006"))
        finally:
            repo.session.flush = original
            repo.session.rollback()
