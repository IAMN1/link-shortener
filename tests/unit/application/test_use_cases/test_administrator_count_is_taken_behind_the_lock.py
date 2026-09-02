"""The administrator count is read behind the lock, not before it.

The lock is what makes counting and writing one decision. Taken after the
count it protects nothing: the number it guards has already been read.

Measured against the running stack before the lock existed, first attempt:
two administrators demoting each other at the same moment both answered
200, and the service was left with no administrator at all -- the state
the count exists to prevent. A row lock cannot express it, because each
request locks the account it is about and the two never touch the same
row; what has to be serialised is the set.
"""

from unittest.mock import Mock

import pytest

from link_shortener.application.use_cases.admin.privilege_guard import (
    require_administrator_remains, require_administrator_survives_without,
)
from link_shortener.domain import DomainError, Permission, Role


ADMIN_ALL = Permission("p-admin", "admin:all", "admin", "all")


@pytest.fixture
def calls():
    """Records the order of the repository calls that matter."""
    return []


@pytest.fixture
def uow(calls):
    """A unit of work whose user repository records its call order."""
    users = Mock()

    def lock():
        calls.append("lock")

    def count(permission, excluding_user_id=None, excluding_role_id=None):
        calls.append("count")
        return 1

    users.lock_administrator_set.side_effect = lock
    users.count_active_with_permission.side_effect = count

    unit = Mock()
    unit.users = users
    return unit


class TestTheOrderOfTheTwoStatements:
    """Both doors into the count take the lock first."""

    def test_re_roling_an_account_locks_before_counting(self, uow, calls):
        require_administrator_remains(uow, "user-1")

        assert calls == ["lock", "count"]

    def test_changing_a_role_locks_before_counting(self, uow, calls):
        role = Role(id="r-1", name="owner", permissions=(ADMIN_ALL,))

        require_administrator_survives_without(uow, role)

        assert calls == ["lock", "count"]

    def test_a_role_that_confers_nothing_takes_no_lock(self, uow, calls):
        """Ordinary role work must not queue behind every other admin change."""
        role = Role(
            id="r-2",
            name="editor",
            permissions=(Permission("p-c", "link:create", "link", "create"),),
        )

        require_administrator_survives_without(uow, role)

        assert calls == []


class TestWhatTheCountIsAskedAbout:
    """The role is excluded from the count, not the account."""

    def test_the_role_is_the_one_disregarded(self, uow):
        role = Role(id="r-1", name="owner", permissions=(ADMIN_ALL,))

        require_administrator_survives_without(uow, role)

        _, kwargs = uow.users.count_active_with_permission.call_args
        assert kwargs == {"excluding_role_id": "r-1"}

    def test_nobody_left_is_a_refusal(self, uow):
        uow.users.count_active_with_permission.side_effect = None
        uow.users.count_active_with_permission.return_value = 0
        role = Role(id="r-1", name="owner", permissions=(ADMIN_ALL,))

        with pytest.raises(DomainError) as refusal:
            require_administrator_survives_without(uow, role)

        assert refusal.value.code == "FORBIDDEN"
