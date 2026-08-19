"""Who reaches ``/api/v1/journals`` and who is turned away.

Against the real authorization service and the real roles table, which is
what the unit tests cannot do: their conftest replaces the service with a
bare ``Mock()``, and a Mock answers truthfully to anything -- so every
permission check in the web layer passes there whether it is present or
not.

Three callers and three journals, because the interesting cases are the
asymmetric ones. A holder of ``logs:view`` who could read the audit journal
would make the split meaningless in the direction that matters, and a
holder of ``audit:view`` who is refused the operational journals is the
same mistake mirrored -- an auditor left unable to correlate an audit entry
with the error it came from.

``admin:all`` is here for the reason it is excluded from ``audit:view`` at
all: an administrator holds every power the audit journal exists to record.
That the exclusion survives the route -- rather than being one of those
rules that holds in the service and is bypassed by the surface -- is only
answerable from here.
"""

from datetime import datetime

import pytest

from tests.integration.conftest import account_with_permissions, auth_headers

from link_shortener.domain import SystemPermissions


JOURNALS = ("application", "error", "audit")

PASSWORD = "Journal1!Reader"


@pytest.fixture(scope="module")
def log_reader(app):
    """An account holding ``logs:view`` and nothing else of interest."""
    client, token, _id = account_with_permissions(
        app,
        email="logs-only@journals.test",
        password=PASSWORD,
        role_name="operational-reader",
        permissions=[SystemPermissions.LOGS_VIEW.value],
    )
    return auth_headers(token)


@pytest.fixture(scope="module")
def audit_reader(app):
    """An account holding ``audit:view`` and nothing else of interest."""
    client, token, _id = account_with_permissions(
        app,
        email="audit-only@journals.test",
        password=PASSWORD,
        role_name="record-reader",
        permissions=[SystemPermissions.AUDIT_VIEW.value],
    )
    return auth_headers(token)


@pytest.fixture(scope="module")
def administrator(app):
    """An account holding the administrative bypass and nothing else."""
    client, token, _id = account_with_permissions(
        app,
        email="admin-only@journals.test",
        password=PASSWORD,
        role_name="bypass-holder",
        permissions=[SystemPermissions.ADMIN_ALL.value],
    )
    return auth_headers(token)


@pytest.fixture(scope="module")
def ordinary(app):
    """An account with the default role and nothing added."""
    client, token, _id = account_with_permissions(
        app,
        email="ordinary@journals.test",
        password=PASSWORD,
        role_name="nothing-in-particular",
        permissions=[SystemPermissions.LINK_VIEW_OWN.value],
    )
    return auth_headers(token)


def read(client, journal, headers=None):
    """
    Ask for one journal.

    Args:
        client: The test client to ask with.
        journal: Name of the journal.
        headers: Authorization headers, or ``None`` for an anonymous ask.

    Returns:
        The response.
    """
    return client.get(f"/api/v1/journals/{journal}", headers=headers or {})


class TestTheOperationalJournalsAndTheRecordAreSeparate:

    @pytest.mark.parametrize("journal", ["application", "error"])
    def test_logs_view_opens_the_operational_journals(
        self, client, log_reader, journal
    ):
        """
        Args:
            journal: The journal ``logs:view`` must open.
        """
        assert read(client, journal, log_reader).status_code == 200

    def test_logs_view_does_not_open_the_audit_journal(self, client, log_reader):
        assert read(client, "audit", log_reader).status_code == 403

    def test_audit_view_opens_the_audit_journal(self, client, audit_reader):
        assert read(client, "audit", audit_reader).status_code == 200

    @pytest.mark.parametrize("journal", ["application", "error"])
    def test_audit_view_does_not_open_the_operational_journals(
        self, client, audit_reader, journal
    ):
        """
        Args:
            journal: The journal ``audit:view`` must not open.
        """
        assert read(client, journal, audit_reader).status_code == 403


class TestTheAdministrativeBypassStopsAtTheRecord:
    """The rule from ``BEYOND_ADMIN_ALL``, asked of the surface."""

    @pytest.mark.parametrize("journal", ["application", "error"])
    def test_an_administrator_reads_the_operational_journals(
        self, client, administrator, journal
    ):
        """
        Args:
            journal: The journal ``admin:all`` must carry.
        """
        assert read(client, journal, administrator).status_code == 200

    def test_an_administrator_is_refused_the_audit_journal(
        self, client, administrator
    ):
        assert read(client, "audit", administrator).status_code == 403


class TestEveryJournalIsClosedToWhoeverHoldsNeitherPermission:

    @pytest.mark.parametrize("journal", JOURNALS)
    def test_an_ordinary_account_is_refused(self, client, ordinary, journal):
        """
        403 rather than 401: the caller was recognised, which is what makes
        this a statement about permissions.

        Args:
            journal: The journal being asked for.
        """
        assert read(client, journal, ordinary).status_code == 403

    @pytest.mark.parametrize("journal", JOURNALS)
    def test_an_anonymous_caller_is_refused(self, client, journal):
        """
        Args:
            journal: The journal being asked for.
        """
        assert read(client, journal).status_code == 401

    def test_no_second_endpoint_serves_a_journal(self, app):
        """
        Guards the guard: these checks are worth nothing if a second way in
        exists. The endpoints that exist are the ones tested; anything else
        handing out journal content would be untested by construction.

        Two now, and the second is not a way to read a journal but a way to
        count one: `/counters` answers with totals and series drawn from
        `security_events`, never with a line. It is listed here anyway,
        because a count is the same information aggregated -- which is why
        it answers to `audit:view` as well, checked below.

        Only the API surface is counted. A dashboard page named after the
        journals serves none of them -- it is a shell that fetches from
        these endpoints -- so including the page here would make this a
        check on which pages happen to exist rather than on where journal
        content comes from.
        """
        serving = {
            str(rule) for rule in app.url_map.iter_rules()
            if "journal" in str(rule) and str(rule).startswith("/api/")
        }

        assert serving == {
            "/api/v1/journals/<journal>",
            "/api/v1/journals/counters",
        }

    def test_the_counters_answer_to_the_audit_permission(
        self, client, administrator, audit_reader
    ):
        """The figures summarise the journal, so they close with it.

        An administrator is refused for the same reason they are refused
        the journal itself: `admin:all` does not carry `audit:view`, and
        these numbers are the record kept about administrators.
        """
        assert client.get(
            "/api/v1/journals/counters", headers=administrator
        ).status_code == 403
        assert client.get(
            "/api/v1/journals/counters", headers=audit_reader
        ).status_code == 200

    def test_the_counters_write_their_moments_the_way_everything_else_does(
        self, client, audit_reader
    ):
        """ISO 8601 in UTC, which is what this codebase means by a moment.

        Serialised without `mode="json"` the two bounds leave as
        `datetime` objects and Flask writes them as RFC 1123 -- "Tue, 18
        Aug 2026 10:46:53 GMT" -- while the schema this endpoint
        publishes says `format: date-time` and the visit chart beside it
        on the same page is handed ISO. A client generated from the
        document cannot parse what the service sends.
        """
        body = client.get(
            "/api/v1/journals/counters", headers=audit_reader
        ).get_json()

        for bound in (body["since"], body["until"]):
            assert datetime.fromisoformat(bound).tzinfo is not None
