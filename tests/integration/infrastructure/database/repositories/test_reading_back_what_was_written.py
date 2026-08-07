"""
Tests that reading a stored link never re-applies an admission rule.

``ALLOWED_SCHEMES`` decides what a client may submit. Applying it again on
the way out makes rows stored under a wider setting unreadable -- and one
such row was enough to fail an entire ``clean-expired`` sweep, so nothing at
all was deleted, and to answer 400 for a link that redirects perfectly well.

This is the defect the email value object had in block 2, in a second place:
a value object built from a database string, refusing the string.
"""

from datetime import datetime, timedelta, timezone

import pytest

from link_shortener.application.context import RequestContext
from link_shortener.domain import OriginalUrl, ShortCode, ValidationError
from link_shortener.infrastructure.database.models.link_model import LinkModel
from link_shortener.infrastructure.database.repositories.sqlalchemy_link_repository import (
    SQLAlchemyLinkRepository,
)


FTP_URL = "ftp://files.example.com/archive.tar"


@pytest.fixture()
def store(app):
    """A repository and its session."""
    with app.app_context():
        db_manager = app.container.get_db_manager()
        with db_manager.session() as session:
            yield SQLAlchemyLinkRepository(session), session


def _row(code, url=FTP_URL, ttl=None):
    """Build an ORM row directly, as a wider configuration would have."""
    now = datetime.now(timezone.utc)
    return LinkModel(
        id=f"scheme-{code}",
        url_hash=f"{abs(hash(code)):064x}"[:64],
        short_code=code,
        original_url=url,
        created_at=now,
        clicks=0,
        expires_at=(now + timedelta(seconds=ttl)) if ttl is not None else None,
    )


class TestAdmissionRulesDoNotApplyOnTheWayOut:
    """A stored URL is read back, not re-admitted."""

    def test_a_scheme_outside_the_default_is_still_readable(self, store):
        repo, session = store
        session.add(_row("schem01"))
        session.commit()

        link = repo.find_by_code(ShortCode("schem01"))

        assert link.original_url.value == FTP_URL

    def test_the_value_object_still_refuses_a_broken_url(self):
        with pytest.raises(ValidationError):
            OriginalUrl.from_storage("not-a-url-at-all")

    def test_the_admission_list_is_not_part_of_identity(self):
        submitted = OriginalUrl("https://example.com/x")
        read_back = OriginalUrl.from_storage("https://example.com/x")

        assert submitted == read_back


class TestOneOddRowDoesNotStopMaintenance:
    """
    The sweep builds an entity per deleted row, so one unreadable row used
    to abort the transaction -- deleting nothing at all, including the
    ordinary expired links next to it.
    """

    def test_the_sweep_clears_ordinary_links_alongside_an_odd_one(self, app, store):
        repo, session = store
        session.add(_row("schem02", ttl=-1))
        session.add(_row("schem03", url="https://example.com/ordinary", ttl=-1))
        session.commit()

        with app.app_context():
            use_case = app.container.get_clean_expired_links_use_case()
            deleted = use_case.execute(RequestContext(request_id="cli-test"))

        assert deleted >= 2
        assert repo.find_by_code(ShortCode("schem02")) is None
        assert repo.find_by_code(ShortCode("schem03")) is None


class TestFormatRulesDoNotApplyOnTheWayOutEither:
    """
    The same argument, one step further.

    A format rule is no less a decision about what may enter, and these
    have moved too: the host label pattern, the ban on control characters
    in the path and the port range are all newer than rows written before
    them. A row they refuse is a row nothing in the product can reach --
    and since the sweep converts a whole chunk before deleting any of it,
    one such row stops every sweep from then on, including the one that
    would have removed it.
    """

    @pytest.mark.parametrize(
        "stored",
        [
            "https://my_host.example.com/legacy",   # underscore in a label
            "https://example.com/a\x01b",           # control character in the path
            "http://example.com:0/x",               # port outside the range
            "https://a..b.com/x",                   # empty label
            "http://127.0.0.1/admin",               # internal, admitted long ago
        ],
    )
    def test_a_row_written_under_older_rules_is_readable(self, stored):
        assert OriginalUrl.from_storage(stored).value == stored

    @pytest.mark.parametrize(
        "stored", ["not-a-url-at-all", "", "http://", "https://x.com:abc/y"]
    )
    def test_a_string_that_is_not_a_url_is_still_refused(self, stored):
        """
        The line is drawn at what has never moved: every version of this
        object has demanded a host, and a string without one cannot be
        normalized, hashed, or put in a Location header.
        """
        with pytest.raises(ValidationError):
            OriginalUrl.from_storage(stored)

    def test_the_sweep_survives_a_row_no_current_rule_would_admit(
        self, app, store
    ):
        repo, session = store
        session.add(_row("fmt001", url="https://my_host.example.com/legacy", ttl=-1))
        session.add(_row("fmt002", url="https://example.com/still-ordinary", ttl=-1))
        session.commit()

        with app.app_context():
            use_case = app.container.get_clean_expired_links_use_case()
            deleted = use_case.execute(RequestContext(request_id="cli-test"))

        assert deleted >= 2
        assert repo.find_by_code(ShortCode("fmt001")) is None
        assert repo.find_by_code(ShortCode("fmt002")) is None
