from unittest.mock import Mock, MagicMock

from link_shortener.application.context import RequestContext
from link_shortener.application.use_cases.links.create_short_link import CreateShortLinkUseCase
from link_shortener.domain import Link, ShortCode, UrlHash, OriginalUrl
from link_shortener.domain import GuestLinkLimitExceededError, ValidationError
import pytest


@pytest.fixture
def mock_uow_factory():
    """Return a factory that yields a mock UoW."""
    uow = Mock()
    factory = Mock(return_value=MagicMock())
    factory.return_value.__enter__ = Mock(return_value=uow)
    factory.return_value.__exit__ = Mock(return_value=False)
    return factory, uow


@pytest.fixture
def mock_cache():
    return Mock()


@pytest.fixture
def mock_hash_calculator():
    calc = Mock()
    calc.calculate.return_value = UrlHash("a" * 64)
    return calc


@pytest.fixture
def mock_code_generator():
    gen = Mock()
    gen.generate_unique.return_value = ShortCode("abc123")
    return gen


@pytest.fixture
def mock_logger():
    logger = Mock()
    logger.bind.return_value = Mock()
    return logger


@pytest.fixture
def mock_audit_logger():
    al = Mock()
    al.bind.return_value = Mock()
    return al


@pytest.fixture
def guest_context():
    return RequestContext(
        request_id="req-1",
        remote_addr="127.0.0.1",
        user_agent="Mozilla/5.0",
        request_path="/api/v1/shorten",
        request_method="POST",
        current_user=None,
    )


@pytest.fixture
def use_case(mock_uow_factory, mock_cache, mock_hash_calculator, mock_code_generator, mock_logger, mock_audit_logger):
    factory, uow = mock_uow_factory
    return CreateShortLinkUseCase(
        uow_factory=factory,
        cache=mock_cache,
        stats_cache=mock_cache,
        hash_calculator=mock_hash_calculator,
        code_generator=mock_code_generator,
        base_url="https://short.link",
        logger=mock_logger,
        audit_logger=mock_audit_logger,
        allowed_schemes=["http", "https"],
        max_url_length=2048,
        allow_internal_targets=False,
        guest_link_limit=10,
        guest_link_window_days=1,
        default_guest_ttl_seconds=604800,
        max_ttl_seconds=10 * 365 * 24 * 3600,
        max_collision_attempts=3,
    )


class TestCreateShortLinkGuest:
    """Tests for guest link creation with TTL."""

    def test_guest_creates_link_with_default_ttl(
        self, use_case, mock_uow_factory, mock_cache, guest_context
    ):
        factory, uow = mock_uow_factory
        mock_cache.get_by_hash.return_value = None
        uow.links.find_live_by_hash.return_value = None
        uow.links.find_by_code.return_value = None
        uow.links.count_guest_links_by_identifier.return_value = 0
        uow.links.save.return_value = Link.create(
            url_hash=UrlHash("a" * 64),
            short_code=ShortCode("abc123"),
            original_url=OriginalUrl("https://example.com"),
        )

        result = use_case.execute("https://example.com", guest_context)

        assert result.is_new is True
        assert result.from_cache is False
        assert result.short_code == "abc123"
        # Guest TTL should be set
        uow.links.save.assert_called_once()
        saved_link = uow.links.save.call_args[0][0]
        assert saved_link.expires_at is not None

    def test_guest_with_custom_ttl(
        self, use_case, mock_uow_factory, mock_cache, guest_context
    ):
        factory, uow = mock_uow_factory
        mock_cache.get_by_hash.return_value = None
        uow.links.find_live_by_hash.return_value = None
        uow.links.find_by_code.return_value = None
        uow.links.count_guest_links_by_identifier.return_value = 0
        uow.links.save.return_value = Link.create(
            url_hash=UrlHash("a" * 64),
            short_code=ShortCode("abc123"),
            original_url=OriginalUrl("https://example.com"),
        )

        result = use_case.execute("https://example.com", guest_context, ttl_seconds=3600)

        assert result.is_new is True
        saved_link = uow.links.save.call_args[0][0]
        assert saved_link.expires_at is not None

    def test_guest_limit_exceeded_raises(
        self, use_case, mock_uow_factory, mock_cache, guest_context
    ):
        factory, uow = mock_uow_factory
        # Nothing to deduplicate against, so this request really would
        # create a link -- which is the only thing the quota charges for.
        mock_cache.get_by_hash.return_value = None
        uow.links.find_live_by_hash.return_value = None
        uow.links.count_guest_links_by_identifier.return_value = 10

        with pytest.raises(GuestLinkLimitExceededError):
            use_case.execute("https://example.com", guest_context)

    def test_invalid_url_raises_validation_error(
        self, use_case, guest_context
    ):
        with pytest.raises(ValidationError):
            use_case.execute("not-a-url", guest_context)
