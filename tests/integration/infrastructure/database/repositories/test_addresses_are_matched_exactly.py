"""Looking an address up must be an equality, not a pattern match.

``Email`` lowers what it holds, so the repository can compare strings and
be done. The tempting follow-up is to make the comparison itself
case-insensitive -- ``ilike`` -- so that rows written before normalisation
are found too. On every database here that is ``LIKE``, where ``_`` and
``%`` are wildcards, and the address rule admits both: ``_`` is ordinary
in local-parts and ``%`` is not excluded by a pattern that only forbids
whitespace and a second ``@``.

What that would buy an attacker, without a single failing test: a lookup
for ``%@example.com`` matches somebody at that domain. Registration would
then answer as though their address were taken, and
``/resend-verification`` would find their unconfirmed account and
invalidate the token they are holding -- a quiet denial of confirmation.

So the operator is pinned here, not merely the outcome for well-behaved
addresses.
"""

import pytest

from link_shortener.domain import Email, PasswordHash, User
from link_shortener.infrastructure.database.repositories.sqlalchemy_user_repository import (
    SQLAlchemyUserRepository,
)


HASH = "$2b$12$" + "x" * 53


@pytest.fixture()
def stored(request):
    """An address with a LIKE metacharacter in it, unique to this test.

    Unique because the application fixture is session-scoped: one database
    serves the whole run, and a constant address is registered by whichever
    test got there first.
    """
    return f"a_b-{request.node.name}@example.test".lower()


@pytest.fixture()
def store(app, stored):
    """A user repository and its session, holding one account."""
    with app.app_context():
        db_manager = app.container.get_db_manager()
        with db_manager.session() as session:
            repository = SQLAlchemyUserRepository(session)
            repository.save(
                User.create(
                    email=Email(stored), password_hash=PasswordHash(HASH)
                )
            )
            session.commit()
            yield repository


class TestAWildcardIsNotAWildcard:
    """Characters that mean something to LIKE must mean nothing here."""

    def test_the_stored_address_is_found_by_itself(self, store, stored):
        assert store.find_by_email(Email(stored)) is not None

    def test_an_underscore_does_not_stand_for_any_character(
        self, app, store, stored
    ):
        """Looked up *with* the underscore, it must not reach the account
        spelled with a letter there.

        The direction matters: it is the lookup that carries the pattern,
        so the account at risk is the one whose address merely resembles
        it.
        """
        neighbour = stored.replace("a_b-", "axb-", 1)
        store.save(
            User.create(
                email=Email(neighbour), password_hash=PasswordHash(HASH)
            )
        )

        assert store.find_by_email(Email(stored)).email.value == stored

    def test_a_percent_matches_nobody(self, store):
        """The one that turns a lookup into a search of the whole domain."""
        assert store.find_by_email(Email("%@example.test")) is None

    def test_a_percent_local_part_matches_nobody(self, store, stored):
        assert store.find_by_email(
            Email(stored.replace("a_b-", "a%b-", 1))
        ) is None


class TestCaseIsHandledBeforeTheQuery:
    """The value object lowers, so the query does not have to -- and must
    not, because a case-insensitive operator here is a pattern match."""

    def test_a_shouted_lookup_still_finds_the_account(self, store, stored):
        assert store.find_by_email(Email(stored.upper())) is not None
