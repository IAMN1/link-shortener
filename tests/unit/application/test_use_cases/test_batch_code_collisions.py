"""
Tests that batch creation never hands out a short code somebody else holds.

Every code it produces goes straight into ``save_many``, and the column is
unique, so reusing one does not degrade the item -- it raises
``IntegrityError`` and fails the entire batch with a 500.
"""

from unittest.mock import Mock

import pytest

from link_shortener.application.use_cases.batch.creator import BatchLinkCreator
from link_shortener.application.use_cases.batch.groups import UrlGroup
from link_shortener.domain import (
    Link, OriginalUrl, OwnerID, ShortCode, UrlHash
)


TAKEN = ShortCode("taken1")
FREE = ShortCode("free01")


def _group(hash_char, url):
    """Build one grouper output entry."""
    return UrlGroup(
        hash=UrlHash(hash_char * 64),
        original_url=OriginalUrl(url),
        urls=[url],
    )


def _stored(code, url_hash, owner="user-a"):
    """Build a link that already occupies a code."""
    from datetime import datetime, timezone

    return Link(
        id="stored-1",
        url_hash=url_hash,
        short_code=code,
        original_url=OriginalUrl("https://example.com/stored"),
        created_at=datetime.now(timezone.utc),
        owner=OwnerID(owner),
    )


@pytest.fixture
def creator():
    """A creator whose generator hands out TAKEN first, then salted codes."""
    generator = Mock()
    generator.generate_for_url.return_value = TAKEN
    generator.generate_unique.side_effect = (
        lambda url, attempt: ShortCode(f"salt{attempt:02d}")
    )
    return BatchLinkCreator(
        code_generator=generator, logger=Mock(), max_attempts=3
    )


class TestACodeInUseIsNeverReissued:
    """Whoever holds the code, the batch has to pick another one."""

    def test_a_code_held_for_the_same_url_is_not_reused(self, creator):
        """
        The link found belongs to another owner.

        Deduplication is per owner, so a link for this very URL can exist
        and still not be the caller's. Creation then proceeds against a
        code that is already occupied, which must not be read as "the same
        URL, reuse it".
        """
        group = _group("a", "https://example.com/same")
        repository = Mock()
        repository.find_by_codes.return_value = {
            TAKEN: _stored(TAKEN, group.hash)
        }

        links = creator.create_new_links(repository, [group])

        assert len(links) == 1
        assert links[0].short_code != TAKEN

    def test_a_code_claimed_earlier_in_the_same_batch_is_not_reused(self):
        """
        The repository lookup cannot know about codes this batch just took.

        Two URLs whose initial codes coincide are a collision like any
        other, even though neither code exists in the database yet.
        """
        generator = Mock()
        generator.generate_for_url.return_value = FREE
        generator.generate_unique.side_effect = (
            lambda url, attempt: ShortCode(f"salt{attempt:02d}")
        )
        creator = BatchLinkCreator(
            code_generator=generator, logger=Mock(), max_attempts=3
        )
        groups = [
            _group("a", "https://example.com/one"),
            _group("b", "https://example.com/two"),
        ]
        repository = Mock()
        repository.find_by_codes.return_value = {FREE: None}

        links = creator.create_new_links(repository, groups)

        codes = [link.short_code for link in links]
        assert len(codes) == len(set(codes)), f"duplicate code issued: {codes}"

    def test_a_salted_replacement_is_checked_against_storage_too(self, creator):
        """
        The replacement is a candidate like any other.

        Asking the repository once, about the initial codes only, left every
        salted replacement checked against nothing but that first answer.
        Two links for one URL in different scopes occupy the first two rungs
        of the ladder, so the batch walked straight onto the second one.
        """
        group = _group("f", "https://example.com/two-rungs")
        repository = Mock()
        # Both the initial code and the first salted rung are taken.
        stored_codes = {TAKEN, ShortCode("salt01")}

        def find_by_codes(codes):
            return {
                code: (_stored(code, group.hash) if code in stored_codes else None)
                for code in codes
            }

        repository.find_by_codes.side_effect = find_by_codes

        links = creator.create_new_links(repository, [group])

        assert len(links) == 1
        assert links[0].short_code not in stored_codes

    def test_a_free_code_is_still_taken_as_is(self, creator):
        group = _group("c", "https://example.com/free")
        repository = Mock()
        repository.find_by_codes.return_value = {TAKEN: None}

        links = creator.create_new_links(repository, [group])

        assert links[0].short_code == TAKEN

    def test_the_salted_ladder_running_out_is_not_the_end(self, creator):
        """
        The ladder is a pure function of the URL, so it is finite.

        Once every rung is taken -- which per-owner deduplication and
        expiry make an ordinary event -- entropy has to take over, rather
        than the item being dropped from the batch.
        """
        group = _group("d", "https://example.com/laddered")
        repository = Mock()
        repository.find_by_codes.return_value = {
            TAKEN: _stored(TAKEN, group.hash)
        }
        creator.code_generator.generate_unique.side_effect = (
            lambda url, attempt: TAKEN
        )
        creator.code_generator.generate_fresh.side_effect = (
            lambda url: ShortCode("fresh1")
        )

        links = creator.create_new_links(repository, [group])

        assert [link.short_code.value for link in links] == ["fresh1"]

    def test_a_hash_that_cannot_be_placed_is_dropped_not_duplicated(self, creator):
        """Exhausting every avenue must skip the item, not reuse a code."""
        group = _group("e", "https://example.com/hopeless")
        repository = Mock()
        repository.find_by_codes.return_value = {
            TAKEN: _stored(TAKEN, group.hash)
        }
        creator.code_generator.generate_unique.side_effect = (
            lambda url, attempt: TAKEN
        )
        creator.code_generator.generate_fresh.side_effect = lambda url: TAKEN

        links = creator.create_new_links(repository, [group])

        assert links == []
