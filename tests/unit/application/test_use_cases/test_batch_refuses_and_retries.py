"""Tests for the two answers batch creation gives that nothing exercised.

Both were written for a reason and neither was ever run. Coverage put five
lines of ``batch_create_links.py`` outside every test in the suite: the
refusal of an oversized batch, and the whole of the retry that exists
because two requests can pick the same short code.

The retry is the one that matters. It was added when the batch started
losing races against concurrent creations, and the single-link path has had
the same loop tested since it grew one -- ``test_concurrent_creation.py``
covers that one, and covers only that one, so the batch's copy of the idea
went in unverified and stayed that way.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from link_shortener.application.dtos.refusal import Refusal
from link_shortener.application.context import RequestContext
from link_shortener.application.use_cases.batch.batch_create_links import (
    BatchCreateLinksUseCase,
)
from link_shortener.application.use_cases.batch.groups import (
    RejectedUrl, UrlGroup,
)
from link_shortener.domain import (
    Link, LinkConflictError, OriginalUrl, ShortCode, UrlHash, ValidationError
)


URL = "https://example.com/batched"


def _link():
    """A link as the creator would have saved it."""
    return Link(
        id="link-1",
        url_hash=UrlHash("b" * 64),
        short_code=ShortCode("btch01"),
        original_url=OriginalUrl(URL),
        created_at=datetime.now(timezone.utc),
    )


def _group():
    """One grouper output entry."""
    return UrlGroup(
        hash=UrlHash("b" * 64), original_url=OriginalUrl(URL), urls=[URL]
    )


@pytest.fixture
def parts():
    """Every collaborator of the use case, stubbed."""
    saved = [_link()]

    grouper = Mock()
    grouper.group.return_value = ([_group()], [])

    fetcher = Mock()
    fetcher.fetch.return_value = ([], [_group()], [])

    creator = Mock()
    # Deliberately unlike the use case's own number, so a test that passes
    # cannot be passing because the two happen to agree.
    creator.max_attempts = 99
    creator.create_new_links.return_value = saved

    builder = Mock()
    builder.build_from_new_links.return_value = []

    uow = Mock()
    uow.links.save_many.return_value = saved
    uow.links.count_guest_links_by_identifier.return_value = 0

    return grouper, fetcher, creator, builder, uow


def _use_case(parts, batch_limit=100, max_collision_attempts=3):
    """Wire the use case up around the stubs."""
    grouper, fetcher, creator, builder, uow = parts

    @contextmanager
    def factory(*args, **kwargs):
        yield uow

    logger = Mock()
    logger.bind.return_value = Mock()
    audit = Mock()
    audit.bind.return_value = Mock()

    return BatchCreateLinksUseCase(
        uow_factory=factory,
        stats_cache=Mock(),
        base_url="https://short.link",
        logger=logger,
        audit_logger=audit,
        batch_limit=batch_limit,
        guest_link_limit=10,
        guest_link_window_days=1,
        default_guest_ttl_seconds=604800,
        max_collision_attempts=max_collision_attempts,
        grouper=grouper,
        fetcher=fetcher,
        creator=creator,
        builder=builder,
    )


def _context():
    return RequestContext(request_id="req-1", remote_addr="198.51.100.20")


class TestABatchLongerThanTheLimitIsRefused:
    """
    The request schema refuses a list longer than ``MAX_BATCH_ITEMS``, but
    ``BATCH_CREATE_LIMIT`` may be set anywhere below that ceiling, and then
    this is the only thing standing between the two numbers. With both at
    their default of 100 the branch cannot be reached through the door at
    all, which is why it went untested -- and why the test has to set the
    limit rather than send a long list.
    """

    def test_the_refusal_names_both_numbers(self, parts):
        use_case = _use_case(parts, batch_limit=2)

        with pytest.raises(ValidationError) as refused:
            use_case.execute([URL, URL, URL], _context())

        assert refused.value.params == {"max": 2, "requested": 3}
        assert refused.value.field == "urls"

    def test_it_is_refused_in_a_sentence_that_can_be_translated(self, parts):
        """The batch's other refusals are marked; this one has to be too.

        A finished f-string reaches the reader in English whatever language
        the request asked for -- the fault the per-item refusals were moved
        off ``str(error)`` to fix.
        """
        use_case = _use_case(parts, batch_limit=1)

        with pytest.raises(ValidationError) as refused:
            use_case.execute([URL, URL], _context())

        assert "%(max)s" in refused.value.template

    def test_a_batch_exactly_at_the_limit_is_not_refused(self, parts):
        """The comparison is ``>``, and an off-by-one here costs an item."""
        use_case = _use_case(parts, batch_limit=1)

        use_case.execute([URL], _context())

    def test_nothing_is_looked_up_for_a_batch_that_is_too_long(self, parts):
        """Refused before the work, which is the point of refusing early."""
        _, fetcher, _, _, _ = parts
        use_case = _use_case(parts, batch_limit=1)

        with pytest.raises(ValidationError):
            use_case.execute([URL, URL], _context())

        fetcher.fetch.assert_not_called()


class TestLosingARaceForACodeRetriesTheWholeTransaction:
    """
    Whether a code is free is settled by the unique index, not by the lookup
    before the insert. On the retry the winner's rows are visible, so the
    resolver picks around them instead of failing the batch.
    """

    def test_a_batch_that_loses_once_still_succeeds(self, parts):
        _, fetcher, _, _, _ = parts
        fetcher.fetch.side_effect = [
            LinkConflictError("lost the race"),
            ([], [_group()], []),
        ]
        use_case = _use_case(parts)

        response = use_case.execute([URL], _context())

        assert fetcher.fetch.call_count == 2
        assert response.total == 0  # builder is stubbed; the point is it ran

    def test_a_batch_that_keeps_losing_is_reported_as_a_conflict(self, parts):
        _, fetcher, _, _, _ = parts
        fetcher.fetch.side_effect = LinkConflictError("lost the race")
        use_case = _use_case(parts, max_collision_attempts=3)

        with pytest.raises(LinkConflictError):
            use_case.execute([URL], _context())

        assert fetcher.fetch.call_count == 3

    def test_the_number_of_attempts_is_the_use_case_s_own(self, parts):
        """Not the creator's, which answers a different question.

        ``BatchLinkCreator.max_attempts`` bounds how many salted codes one
        hash is offered before it is given up on. Reading the transaction's
        retry count off it tied two decisions to one number and made either
        one impossible to change alone. The stub's creator says 99 here; if
        that were still the source, this batch would be attempted 99 times.
        """
        _, fetcher, creator, _, _ = parts
        fetcher.fetch.side_effect = LinkConflictError("lost the race")
        use_case = _use_case(parts, max_collision_attempts=2)

        with pytest.raises(LinkConflictError):
            use_case.execute([URL], _context())

        assert creator.max_attempts == 99
        assert fetcher.fetch.call_count == 2


class TestEveryExitReportsHowLongItTook:
    """
    ``processing_time_seconds`` is documented as the batch's execution
    time, and the use case measures it. It reached the response through
    the last return only, so the two answers a caller is most likely to be
    timing -- a batch of nothing and a batch that was all malformed --
    reported 0.0 for work that had been done.
    """

    def test_a_batch_of_only_malformed_urls_still_reports_a_duration(
        self, parts
    ):
        grouper, _, _, _, _ = parts
        grouper.group.return_value = (
            [],
            [RejectedUrl(url="not-a-url", refusal=Refusal.of("bad", "X"))],
        )
        use_case = _use_case(parts)

        response = use_case.execute(["not-a-url"], _context())

        assert response.failed == 1
        assert response.processing_time_seconds > 0

    def test_the_ordinary_answer_reports_one_too(self, parts):
        use_case = _use_case(parts)

        response = use_case.execute([URL], _context())

        assert response.processing_time_seconds > 0

    def test_a_batch_of_nothing_reports_one_as_well(self, parts):
        """The third exit, and the one that had a factory of its own.

        ``BatchCreateResponse.empty()`` built the same object
        ``from_results([])`` builds, minus the duration -- a second way to
        say the same thing, whose only caller was the one return that then
        could not say it.
        """
        use_case = _use_case(parts)

        response = use_case.execute([], _context())

        assert response.total == 0
        assert response.processing_time_seconds > 0
