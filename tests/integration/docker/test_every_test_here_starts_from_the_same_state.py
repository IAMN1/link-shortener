"""
The state this directory promises each of its tests.

`app` is session-scoped and seeds the base roles once; `_clean_db` is
autouse and truncates `roles` and `permissions` after every test. So the
seeded state belonged to whichever test ran first, and every test after
it saw an empty table -- measured before this was fixed: five roles in the
first test of a file, none in the second.

Nothing had failed of it, because the tests here happen to build what
they need. What it meant is that a test needing a role would pass alone
and in first position and fail anywhere else, which is the kind of
failure that gets read as flakiness and retried.

Two tests, deliberately, and the second is the one that matters: a single
test asking this question is always the first one.
"""

from sqlalchemy import text


SEEDED = {"admin", "analyst", "auditor", "guest", "user"}


def role_names(app):
    """The roles the database carries right now."""
    with app.app_context():
        with app.container.get_db_manager().session() as session:
            return {
                row[0]
                for row in session.execute(text("SELECT name FROM roles"))
            }


class TestTheBaseRolesAreThereForEveryTest:

    def test_they_are_there_for_the_first_test(self, app):
        """The half that always passed."""
        assert role_names(app) == SEEDED

    def test_they_are_still_there_for_the_next_one(self, app):
        """
        The half that did not. This runs after a truncation, so it asks
        whether the cleaning puts back what the fixture promised rather
        than whether it ran at all.
        """
        assert role_names(app) == SEEDED

    def test_a_role_written_by_one_test_does_not_reach_the_next(self, app):
        """
        The other direction, which is why the roles are re-seeded rather
        than spared by the truncation: a role an earlier test created has
        to be gone, or the cleaning is not cleaning.
        """
        with app.app_context():
            with app.container.get_db_manager().session() as session:
                session.execute(
                    text(
                        "INSERT INTO roles (id, name, description, is_system) "
                        "VALUES ('leftover', 'leftover-role', "
                        "'from a test', false)"
                    )
                )
                session.commit()

        assert "leftover-role" in role_names(app)

    def test_and_it_is_gone_by_the_test_after(self, app):
        assert role_names(app) == SEEDED
