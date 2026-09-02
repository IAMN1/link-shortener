"""
Deleting a role leaves accounts wearing nothing, and what happens next.

The use case puts those accounts back on the default role. Two things
about that were missing, and both were found by a review of this branch.

**It left no record.** An account silently gained the default role's
permissions -- a change to what it may do, which is the rule the audit
vocabulary is built on. An investigator asking "why does this account hold
`user`" had nothing to read: the deletion is recorded, the re-roling was
not.

**A refusal from the re-roling undid the deletion.** ``update_roles`` asks
the assignability policy, so a deployment that has pointed
``DEFAULT_ROLE_NAME`` at something unassignable -- ``guest``, say -- raised
out of the loop before ``uow.commit()``. The role deletion went back with
it, and the operator was told the role could not be deleted, naming a
reason that had nothing to do with the role. The branch above it, for a
missing fallback, already chose the other way: say it, keep the
transaction, the role is gone either way.
"""

from unittest.mock import MagicMock

from link_shortener.application.context import RequestContext
from link_shortener.application.use_cases.admin.roles.delete_role import (
    DeleteRoleUseCase,
)
from link_shortener.domain.exceptions import DomainError


DOOMED = "doomed-role"
FALLBACK = "user"
WEARER = "the-account"


def a_use_case(reroll_raises: bool = False):
    """The use case with every port stubbed, and the accounts it will find."""
    doomed = MagicMock()
    doomed.id = "doomed-id"
    fallback = MagicMock()
    fallback.name = FALLBACK

    bare_account = MagicMock()
    bare_account.roles = []

    uow = MagicMock()
    uow.__enter__.return_value = uow
    uow.__exit__.return_value = False
    uow.roles.get_by_name.side_effect = lambda name: (
        doomed if name == DOOMED else fallback
    )
    uow.users.count_with_role.return_value = 1
    uow.users.ids_with_role.return_value = [WEARER]
    uow.users.find_by_id.return_value = bare_account

    user_service = MagicMock()
    if reroll_raises:
        user_service.update_roles.side_effect = DomainError(
            "Role 'guest' cannot be assigned to an account",
            code="ROLE_NOT_ASSIGNABLE",
        )

    audit = MagicMock()
    audit.bind.return_value = audit

    use_case = DeleteRoleUseCase(
        uow_factory=MagicMock(return_value=uow),
        role_service=MagicMock(),
        user_service=user_service,
        logger=MagicMock(),
        audit_logger=audit,
        default_role_name=FALLBACK,
    )
    return use_case, audit, uow


def context():
    return RequestContext(request_id="delete-role-test")


class TestPuttingAWearerBackIsOnTheRecord:

    def test_the_change_of_roles_is_recorded(self):
        use_case, audit, _ = a_use_case()

        use_case.execute(DOOMED, context())

        audit.log_roles_changed.assert_called_once()

    def test_the_record_names_the_account_and_both_roles(self):
        """
        Which account, what it lost and what it gained -- the three facts
        the question "why does this account hold `user`" is asking for.
        """
        use_case, audit, _ = a_use_case()

        use_case.execute(DOOMED, context())

        _, kwargs = audit.log_roles_changed.call_args
        assert kwargs["target_user_id"] == WEARER
        assert kwargs["roles_before"] == [DOOMED]
        assert kwargs["roles_after"] == [FALLBACK]

    def test_the_deletion_itself_is_still_recorded(self):
        """The record that was already there has to stay."""
        use_case, audit, _ = a_use_case()

        use_case.execute(DOOMED, context())

        audit.log_role_deleted.assert_called_once()


class TestARefusalFromTheRerolingDoesNotUndoTheDeletion:
    """
    The transaction is worth keeping, as the missing-fallback branch says.
    """

    def test_the_deletion_is_committed(self):
        use_case, _, uow = a_use_case(reroll_raises=True)

        use_case.execute(DOOMED, context())

        uow.commit.assert_called_once()

    def test_nothing_is_recorded_about_a_reroling_that_did_not_happen(self):
        use_case, audit, _ = a_use_case(reroll_raises=True)

        use_case.execute(DOOMED, context())

        audit.log_roles_changed.assert_not_called()

    def test_the_refusal_does_not_reach_the_caller(self):
        """
        The role is gone; answering "could not delete" would be false, and
        naming the fallback's policy would name the wrong subject.
        """
        use_case, _, _ = a_use_case(reroll_raises=True)

        use_case.execute(DOOMED, context())
