"""
Tests that the list of accounts comes back in an order.

``list_all`` pages -- the admin API takes ``limit`` and ``offset``, and the
panel walks it fifty rows at a time -- and paging an unordered query is
paging nothing: the database is free to hand the rows over differently
between two requests, and PostgreSQL does, because the order it falls back
on is where the row physically sits.

Measured on the running stack before this was fixed: twelve accounts, two
windows of six, then ``POST /api/v1/admin/users/<id>/deactivate`` on the
account at the top of the first window. It moved to the far end of the
table and appeared on neither page. A signed-in administrator does the
same to themselves, since signing in writes ``last_login``.

SQLite, which the suite runs on, does not move a row on update -- so what
is checked here is not that measurement but the property underneath it:
rows stored out of address order are listed in address order, and a window
into the listing holds what that order puts there.
"""

from datetime import datetime, timedelta, timezone

import pytest

from link_shortener.infrastructure.database.models.user_model import UserModel
from link_shortener.infrastructure.database.repositories.sqlalchemy_user_repository import (
    SQLAlchemyUserRepository,
)


# Stored newest first, so insertion order is the reverse of address order:
# a listing that repeats whatever the table hands over gives itself away
# on either count.
STORED = [("delta", 1), ("alpha", 2), ("charlie", 3), ("bravo", 4)]


@pytest.fixture()
def four_accounts(app, request):
    """
    Four accounts of this test's own, stored out of address order.

    Addresses carry the test's name, because the application fixture is
    built once for the session and every account any test writes is still
    there. The listing under test is the whole table, so these are picked
    back out of it by that prefix, and removed afterwards.

    Returns:
        The repository, and the four addresses in the order they belong in.
    """
    tag = request.node.name.replace("_", "-")[:40]
    with app.app_context():
        db_manager = app.container.get_db_manager()
        with db_manager.session() as session:
            for local_part, age in STORED:
                session.add(
                    UserModel(
                        id=f"ordered-{tag}-{local_part}",
                        email=f"{local_part}-{tag}@example.com",
                        password_hash="$2b$12$not-a-real-hash---------------",
                        is_active=True,
                        email_verified=True,
                        created_at=datetime.now(timezone.utc)
                        - timedelta(days=age),
                    )
                )
            session.commit()

            expected = sorted(
                f"{local_part}-{tag}@example.com" for local_part, _ in STORED
            )
            yield SQLAlchemyUserRepository(session), expected, tag

            session.query(UserModel).filter(
                UserModel.id.like(f"ordered-{tag}-%")
            ).delete(synchronize_session=False)
            session.commit()


def _mine(users, tag):
    """The addresses of this test's own accounts, in the order listed."""
    return [u.email.value for u in users if f"-{tag}@" in u.email.value]


class TestTheListingHasAnOrder:

    def test_accounts_come_back_in_address_order(self, four_accounts):
        repo, expected, tag = four_accounts

        listed = repo.list_all(limit=1000)

        assert _mine(listed, tag) == expected

    def test_a_window_is_a_slice_of_the_listing(self, four_accounts):
        """
        Not the whole listing but a slice of it, which is what the panel
        and the admin API actually ask for.

        Against the whole table rather than against these four accounts:
        the application fixture is built once for the session, so other
        tests' accounts sit between them by address and a window is not
        theirs to predict.

        The slice is taken out of the listing **sorted here**, not out of
        the listing as it arrived. Compared against the arrival order,
        this test would be comparing one call with another call of the
        same query -- true of an unordered listing on SQLite as readily
        as of an ordered one, and green with the ``ORDER BY`` taken out.
        """
        repo, expected, _ = four_accounts
        everyone = sorted(u.email.value for u in repo.list_all(limit=2000))
        depth = everyone.index(expected[0])

        window = repo.list_all(limit=3, offset=depth)

        assert [u.email.value for u in window] == everyone[depth:depth + 3]

    def test_the_same_window_answers_the_same_twice(self, four_accounts):
        """
        The property paging rests on: the answer is a function of the
        window asked for, not of the table's mood. Nothing writes in
        between -- that is the point.

        Sorted here for the reason the test above gives, so that "the
        same answer twice" is the same *right* answer twice.
        """
        repo, expected, _ = four_accounts
        everyone = sorted(u.email.value for u in repo.list_all(limit=2000))
        depth = everyone.index(expected[0])

        once = [u.email.value for u in repo.list_all(limit=3, offset=depth)]
        twice = [u.email.value for u in repo.list_all(limit=3, offset=depth)]

        assert once == twice == everyone[depth:depth + 3]

    def test_two_windows_side_by_side_do_not_overlap(self, four_accounts):
        """
        What the panel does: page one, then page two. An account shown on
        both, or on neither, is the failure this file is about.

        Sorted here for the reason the two tests above give.
        """
        repo, expected, _ = four_accounts
        everyone = sorted(u.email.value for u in repo.list_all(limit=2000))
        depth = everyone.index(expected[0])

        first = [u.email.value for u in repo.list_all(limit=2, offset=depth)]
        second = [
            u.email.value for u in repo.list_all(limit=2, offset=depth + 2)
        ]

        assert not set(first) & set(second), "an account is on both pages"
        assert first + second == everyone[depth:depth + 4]
