"""
Tests that an owner-less link has exactly one shape.

The repository returned ``owner=None`` for a guest link while the factory and
the cache returned ``OwnerID(None)``. The same link therefore arrived
differently depending on which of the three had produced it, and every
comparison between two such copies was quietly wrong.
"""

import json
from unittest.mock import Mock

import pytest

from link_shortener.domain import (
    Link, OriginalUrl, OwnerID, ShortCode, UrlHash, ValidationError
)
from link_shortener.infrastructure.cache.redis_cache import RedisLinkCache
from link_shortener.infrastructure.database.repositories.sqlalchemy_link_repository import (
    SQLAlchemyLinkRepository,
)


HASH = UrlHash("b" * 64)
CODE = "own123"


class TestThereIsNoSuchThingAsAnEmptyOwnerId:
    """The value object refuses the shape that caused the mismatch."""

    def test_none_is_refused(self):
        with pytest.raises(ValidationError):
            OwnerID(None)

    def test_an_empty_string_is_refused(self):
        with pytest.raises(ValidationError):
            OwnerID("")


class TestEveryProducerAgrees:
    """Factory, repository and cache must return the same shape."""

    def test_the_factory_leaves_a_guest_link_without_an_owner(self):
        link = Link.create(
            url_hash=HASH,
            short_code=ShortCode(CODE),
            original_url=OriginalUrl("https://example.com/x"),
            guest_identifier="203.0.113.8",
        )

        assert link.owner is None

    def test_the_repository_leaves_a_guest_link_without_an_owner(self):
        repo = SQLAlchemyLinkRepository(Mock())
        model = Mock()
        model.id = "link-1"
        model.url_hash = HASH.value
        model.short_code = CODE
        model.original_url = "https://example.com/x"
        model.created_at = None
        model.clicks = 0
        model.last_accessed = None
        model.owner_id = None
        model.expires_at = None
        model.guest_identifier = "203.0.113.8"

        assert repo._to_domain(model).owner is None

    def test_the_cache_leaves_a_guest_link_without_an_owner(self):
        cache = RedisLinkCache.__new__(RedisLinkCache)
        cache.logger = Mock()
        payload = json.dumps({
            "id": "link-1",
            "url_hash": HASH.value,
            "short_code": CODE,
            "original_url": "https://example.com/x",
            "created_at": "2026-08-06T10:00:00+00:00",
            "clicks": 0,
            "last_accessed": None,
            "owner_id": None,
            "expires_at": None,
            "guest_identifier": "203.0.113.8",
        }).encode("utf-8")

        assert cache._deserialize(payload).owner is None

    def test_an_owned_link_keeps_its_owner_everywhere(self):
        link = Link.create(
            url_hash=HASH,
            short_code=ShortCode(CODE),
            original_url=OriginalUrl("https://example.com/x"),
            owner=OwnerID("user-a"),
        )

        assert link.owner == OwnerID("user-a")
