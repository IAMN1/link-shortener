"""What the route does with the address and the query string.

The permission decision belongs to the use case and is tested there, over
the real authorization service; what is left for the route is the part the
use case never sees -- a journal named by a string, a limit arriving as
text, and a body assembled from a page.

The use case is a mock here for exactly that reason. Its own tests build it
over the real RBAC service; these ask whether the route hands it the right
journal and the right numbers, and a route that quietly passed
``limit="200"`` as a string would fail here and nowhere else.
"""

import json
from unittest.mock import Mock

import pytest

from link_shortener.application.ports.journal_reader import (
    Journal, JournalLine, JournalPage,
)
from link_shortener.domain import DomainError
from link_shortener.infrastructure.di.container import Container
from link_shortener.infrastructure.logging.journal_reader import HARD_LIMIT
from link_shortener.web.app_factory import create_app


def a_page(lines=(), **overrides) -> JournalPage:
    """
    A page with the given lines and otherwise unremarkable metadata.

    Args:
        lines: The ``JournalLine`` values it holds.
        overrides: Fields to set differently.

    Returns:
        The page.
    """
    fields = {
        "lines": tuple(lines),
        "total_scanned": len(lines),
        "reached_start": False,
        "files_read": ("application.log",),
        "oldest_available": None,
    }
    fields.update(overrides)
    return JournalPage(**fields)


@pytest.fixture
def read_journal():
    """The use case the route calls, standing in for the real one."""
    use_case = Mock()
    use_case.execute.return_value = a_page()
    return use_case


@pytest.fixture
def journal_api(test_config, read_journal, monkeypatch):
    """
    The real application, with only the journal use case replaced.

    Named away from ``app`` deliberately: the autouse fixture in this
    package's ``conftest`` replaces the template loader of any fixture
    called that, and everything else it mocks is beside the point here.
    """
    monkeypatch.setattr(
        Container, "get_read_journal_use_case", lambda self: read_journal
    )
    monkeypatch.setattr(Container, "close", lambda self: None)
    application = create_app(config=test_config)
    return application.test_client()


def body_of(response):
    """
    Decode a JSON response.

    Args:
        response: The Flask test response.

    Returns:
        The decoded body.
    """
    return json.loads(response.data)


class TestTheNameInTheAddressBecomesAJournal:

    @pytest.mark.parametrize("name, expected", [
        pytest.param("application", Journal.APPLICATION, id="application"),
        pytest.param("error", Journal.ERROR, id="error"),
        pytest.param("audit", Journal.AUDIT, id="audit"),
    ])
    def test_each_of_the_three_reaches_the_use_case_as_its_member(
        self, journal_api, read_journal, name, expected
    ):
        """
        Args:
            name: The name as it appears in the address.
            expected: The member it must arrive as.
        """
        assert journal_api.get(f"/api/v1/journals/{name}").status_code == 200

        assert read_journal.execute.call_args.args[0] is expected

    @pytest.mark.parametrize("name", [
        pytest.param("applications", id="near-miss"),
        pytest.param("Audit", id="wrong-case"),
        pytest.param("audit.log", id="the-file-name"),
        pytest.param("application.log.1", id="an-archive"),
        pytest.param("%2e%2e", id="dots-escaped"),
    ])
    def test_anything_else_is_404_and_never_reaches_the_use_case(
        self, journal_api, read_journal, name
    ):
        """
        The enum is what makes a path unspellable, and the conversion
        happens before anything else: a name that is not a journal is
        refused as a name rather than as a permission.

        Args:
            name: A name no journal has.
        """
        response = journal_api.get(f"/api/v1/journals/{name}")

        assert response.status_code == 404
        assert body_of(response)["error"] == "JOURNAL_NOT_FOUND"
        read_journal.execute.assert_not_called()

    def test_a_name_carrying_a_separator_never_reaches_the_route_at_all(
        self, journal_api, read_journal
    ):
        """
        Two layers, and the outer one answers first.

        ``%2f`` is decoded before routing, and the default converter does
        not match across a separator -- so ``../../etc/passwd`` is not a
        journal this route refuses, it is a path this route does not have.
        The answer is Flask's own 404 rather than ``JOURNAL_NOT_FOUND``,
        which is worth pinning: a converter widened later to accept
        ``path`` would move this case inside the route, and the enum would
        then be the only thing standing between a query string and a file
        name.
        """
        response = journal_api.get("/api/v1/journals/..%2f..%2fetc%2fpasswd")

        assert response.status_code == 404
        assert body_of(response)["error"] == "NOT_FOUND"
        read_journal.execute.assert_not_called()


class TestTheQueryStringIsValidatedRatherThanRead:

    def test_the_defaults_ask_for_the_live_journal(
        self, journal_api, read_journal
    ):
        journal_api.get("/api/v1/journals/application")

        assert read_journal.execute.call_args.kwargs == {
            "limit": 200, "include_archives": False, "following": False
        }

    def test_a_limit_arrives_as_a_number(self, journal_api, read_journal):
        """``limit="50"`` reaches ``min()`` in the reader as a string, where
        Python 3 refuses to compare it with an integer at all."""
        journal_api.get("/api/v1/journals/application?limit=50")

        assert read_journal.execute.call_args.kwargs["limit"] == 50

    @pytest.mark.parametrize("asked", [
        pytest.param("0", id="none-at-all"),
        pytest.param("-5", id="negative"),
        pytest.param(str(HARD_LIMIT + 1), id="past-the-ceiling"),
        pytest.param("all", id="not-a-number"),
    ])
    def test_a_limit_outside_the_range_is_refused(
        self, journal_api, read_journal, asked
    ):
        """
        Refused rather than trimmed. A caller who asked for ten thousand
        lines and silently got two thousand has been told the journal holds
        two thousand lines.

        Args:
            asked: The value sent as ``limit``.
        """
        response = journal_api.get(f"/api/v1/journals/audit?limit={asked}")

        assert response.status_code == 400
        assert body_of(response)["error"] == "VALIDATION_ERROR"
        read_journal.execute.assert_not_called()

    @pytest.mark.parametrize("sent, expected", [
        pytest.param("true", True, id="true"),
        pytest.param("1", True, id="one"),
        pytest.param("false", False, id="false"),
        pytest.param("0", False, id="zero"),
    ])
    def test_the_archives_flag_is_read_as_a_boolean(
        self, journal_api, read_journal, sent, expected
    ):
        """
        Args:
            sent: The value sent as ``archives``.
            expected: What must reach the use case.
        """
        journal_api.get(f"/api/v1/journals/error?archives={sent}")

        assert read_journal.execute.call_args.kwargs["include_archives"] is expected


class TestTheBodyCarriesWhatThePageKnows:

    def test_a_line_goes_out_with_its_fields_and_its_source(
        self, journal_api, read_journal
    ):
        read_journal.execute.return_value = a_page([
            JournalLine(
                raw='{"event": "Link created"}',
                fields={"event": "Link created"},
                parsed=True,
                source="audit.log",
            ),
        ])

        body = body_of(journal_api.get("/api/v1/journals/audit"))

        assert body["journal"] == "audit"
        assert body["lines"] == [{
            "raw": '{"event": "Link created"}',
            "fields": {"event": "Link created"},
            "parsed": True,
            "source": "audit.log",
        }]

    def test_a_line_nothing_could_read_is_sent_marked_rather_than_dropped(
        self, journal_api, read_journal
    ):
        """A viewer that omits what it cannot parse is least trustworthy
        exactly when it matters -- a write torn by rotation, a traceback a
        library printed itself."""
        read_journal.execute.return_value = a_page([
            JournalLine(
                raw="Traceback (most recent call last):",
                fields={},
                parsed=False,
                source="error.log",
            ),
        ])

        body = body_of(journal_api.get("/api/v1/journals/error"))

        assert body["lines"][0]["parsed"] is False
        assert body["lines"][0]["raw"] == "Traceback (most recent call last):"

    def test_how_far_back_the_answer_reached_is_reported(
        self, journal_api, read_journal
    ):
        """``reached_start`` and ``oldest_available`` are what keep a reader
        from taking the start of a rotated file for the start of history."""
        read_journal.execute.return_value = a_page(
            reached_start=True,
            files_read=("audit.log", "audit.log.1"),
            oldest_available="audit.log.14.gz",
        )

        body = body_of(journal_api.get("/api/v1/journals/audit"))

        assert body["reached_start"] is True
        assert body["files_read"] == ["audit.log", "audit.log.1"]
        assert body["oldest_available"] == "audit.log.14.gz"


class TestARefusalFromTheUseCaseIsPassedOn:
    """The route does not decide these, and must not swallow them either."""

    @pytest.mark.parametrize("code, status", [
        pytest.param("UNAUTHENTICATED", 401, id="nobody-signed-in"),
        pytest.param("FORBIDDEN", 403, id="wrong-permission"),
    ])
    def test_the_status_matches_the_refusal(
        self, journal_api, read_journal, code, status
    ):
        """
        Args:
            code: The refusal the use case raised.
            status: The status the caller must see.
        """
        read_journal.execute.side_effect = DomainError("no", code=code)

        response = journal_api.get("/api/v1/journals/audit")

        assert response.status_code == status
        assert body_of(response)["error"] == code
