"""
Tests for what deduplication is allowed to hand back on the create path.

The cache is a real ``InMemoryLinkCache`` rather than a mock: the thing under
test is whether an entry written for one caller can answer another, and that
question lives in the key the cache builds. A mock would answer whatever the
test told it to.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, Mock

import pytest

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.current_user_info import CurrentUserInfo
from link_shortener.application.use_cases.links.create_short_link import (
    CreateShortLinkUseCase,
)
from link_shortener.domain import (
    DedupScope, Link, OriginalUrl, OwnerID, ShortCode, UrlHash,
    ValidationError,
)
from link_shortener.infrastructure.cache.memory_cache import InMemoryLinkCache


URL = "https://example.com/dedup"
HASH = UrlHash("a" * 64)
EXISTING_CODE = "old123"
NEW_CODE = "new123"


@pytest.fixture
def cache():
    """A real in-memory cache, so scoping is exercised rather than mocked."""
    return InMemoryLinkCache(prefix="test", link_ttl=3600, stats_ttl=60)


@pytest.fixture
def uow():
    """A mock unit of work whose repository answers nothing by default."""
    repo = Mock()
    repo.find_by_code.return_value = None
    repo.find_live_by_hash.return_value = None
    repo.count_guest_links_by_identifier.return_value = 0
    repo.save.side_effect = lambda link: link

    unit = Mock()
    unit.links = repo
    return unit


@pytest.fixture
def use_case(cache, uow):
    """Use case wired to the real cache and the mock unit of work."""
    @contextmanager
    def factory(*args, **kwargs):
        yield uow

    hash_calculator = Mock()
    hash_calculator.calculate.return_value = HASH

    code_generator = Mock()
    code_generator.generate_unique.return_value = ShortCode(NEW_CODE)

    logger = Mock()
    logger.bind.return_value = Mock()
    audit_logger = Mock()
    audit_logger.bind.return_value = Mock()

    return CreateShortLinkUseCase(
        uow_factory=factory,
        cache=cache,
        stats_cache=cache,
        hash_calculator=hash_calculator,
        code_generator=code_generator,
        base_url="https://short.link",
        logger=logger,
        audit_logger=audit_logger,
        allowed_schemes=["http", "https"],
        max_url_length=2048,
        allow_internal_targets=False,
        guest_link_limit=10,
        guest_link_window_days=1,
        default_guest_ttl_seconds=604800,
        max_ttl_seconds=10 * 365 * 24 * 3600,
        max_collision_attempts=3,
    )


def _link(code=EXISTING_CODE, owner=None, guest=None, ttl=0, clicks=0):
    """
    Build a stored link.

    Args:
        code: Short code.
        owner: Owner id, or ``None``.
        guest: Guest identifier, or ``None``.
        ttl: Seconds until expiry; negative for an expired link.
        clicks: Click counter.

    Returns:
        A Link entity.
    """
    now = datetime.now(timezone.utc)
    return Link(
        id="link-1",
        url_hash=HASH,
        short_code=ShortCode(code),
        original_url=OriginalUrl(URL),
        created_at=now,
        clicks=clicks,
        owner=OwnerID(owner) if owner else None,
        expires_at=(now + timedelta(seconds=ttl)) if ttl else None,
        guest_identifier=guest,
    )


def _answers_only_for(code_value, link):
    """
    Build a ``find_by_code`` stub that knows about exactly one code.

    Any other code -- notably the freshly generated one -- must come back
    free, or code generation reads a collision and gives up.

    Args:
        code_value: The code the stub knows.
        link: What to return for it.

    Returns:
        A callable for ``Mock.side_effect``.
    """
    return lambda code: link if code.value == code_value else None


def _context(user_id=None, ip="198.51.100.7"):
    """
    Build a request context.

    Args:
        user_id: Authenticated user id, or ``None`` for a guest.
        ip: Client address.

    Returns:
        A RequestContext.
    """
    user = (
        CurrentUserInfo(id=user_id, email="u@example.com", roles=[], is_active=True)
        if user_id
        else None
    )
    return RequestContext(
        request_id="req-1",
        remote_addr=ip,
        request_path="/api/v1/shorten",
        request_method="POST",
        current_user=user,
    )


class TestACachedHitIsConfirmedBeforeItIsServed:
    """
    The cache says a link existed; only the repository knows if it still does.

    Under ``allkeys-lru`` the entry outliving the row is routine, and serving
    it unchecked answered "200, not new" with a code that gives 404 or 410.
    """

    def test_an_entry_whose_link_is_gone_is_not_served(self, use_case, cache, uow):
        stored = _link(owner="user-a")
        cache.save(stored)
        uow.links.find_by_code.return_value = None   # deleted since

        result = use_case.execute(URL, _context(user_id="user-a"))

        assert result.is_new is True
        assert result.short_code == NEW_CODE

    def test_the_dead_entry_is_dropped_rather_than_left_to_repeat(
        self, use_case, cache, uow
    ):
        cache.save(_link(owner="user-a"))
        uow.links.find_by_code.return_value = None

        use_case.execute(URL, _context(user_id="user-a"))

        # What sits there now is the link that was just created, not the
        # dead code that would otherwise be offered again on every request.
        entry = cache.get_by_hash(HASH, DedupScope.for_owner("user-a"))
        assert entry.short_code.value == NEW_CODE

    def test_an_entry_whose_link_expired_is_not_served(self, use_case, cache, uow):
        cache.save(_link(owner="user-a", ttl=3600))
        # The row is still there, but it has expired since the entry was written.
        uow.links.find_by_code.side_effect = _answers_only_for(
            EXISTING_CODE, _link(owner="user-a", ttl=-1)
        )

        result = use_case.execute(URL, _context(user_id="user-a"))

        assert result.is_new is True
        assert result.short_code == NEW_CODE

    def test_an_entry_whose_link_changed_hands_is_not_served(
        self, use_case, cache, uow
    ):
        cache.save(_link(owner="user-a"))
        uow.links.find_by_code.side_effect = _answers_only_for(
            EXISTING_CODE, _link(owner="user-b")
        )

        result = use_case.execute(URL, _context(user_id="user-a"))

        assert result.is_new is True

    def test_a_confirmed_hit_answers_with_the_stored_row(self, use_case, cache, uow):
        cache.save(_link(owner="user-a", clicks=0))
        # The database has moved on since the entry was written.
        uow.links.find_by_code.return_value = _link(owner="user-a", clicks=42)

        result = use_case.execute(URL, _context(user_id="user-a"))

        assert result.is_new is False
        assert result.from_cache is True
        assert result.short_code == EXISTING_CODE
        assert result.clicks == 42


def _looked_up(uow, code_value):
    """
    Report whether the repository was asked about a specific code.

    ``find_by_code`` is also used to check a freshly generated code for
    collisions, so "was it called at all" says nothing.

    Args:
        uow: The mock unit of work.
        code_value: Code to look for among the calls.

    Returns:
        True if the code was looked up.
    """
    return any(
        call.args[0].value == code_value
        for call in uow.links.find_by_code.call_args_list
    )


class TestTheCacheAnswersOnlyItsOwnScope:
    """An entry written for one caller must be invisible to another."""

    def test_another_users_entry_is_never_read(self, use_case, cache, uow):
        cache.save(_link(owner="user-a"))

        use_case.execute(URL, _context(user_id="user-b"))

        # Not merely refused after being read: the lookup must not find it,
        # so the foreign code is never even checked.
        assert not _looked_up(uow, EXISTING_CODE)

    def test_a_guests_entry_is_not_read_by_a_registered_user(
        self, use_case, cache, uow
    ):
        cache.save(_link(guest="198.51.100.7"))

        use_case.execute(URL, _context(user_id="user-a"))

        assert not _looked_up(uow, EXISTING_CODE)

    def test_another_guests_entry_is_not_read(self, use_case, cache, uow):
        cache.save(_link(guest="203.0.113.1"))

        use_case.execute(URL, _context(ip="198.51.100.7"))

        assert not _looked_up(uow, EXISTING_CODE)


class TestTheRepositoryIsAskedWithinTheCallersScope:
    """The scope reaches the repository, not just the cache."""

    def test_a_registered_user_asks_as_themselves(self, use_case, uow):
        use_case.execute(URL, _context(user_id="user-a"))

        _, scope = uow.links.find_live_by_hash.call_args[0]
        assert scope == DedupScope.for_owner("user-a")

    def test_a_guest_asks_as_their_address(self, use_case, uow):
        use_case.execute(URL, _context(ip="198.51.100.7"))

        _, scope = uow.links.find_live_by_hash.call_args[0]
        assert scope == DedupScope.for_guest("198.51.100.7")


class TestAnInternalFailureIsNotReportedAsBadInput:
    """
    ``except ValueError`` used to wrap the whole of ``execute``.

    Everything inside it -- the cache read, the repository, the unit of work
    -- came back to the caller as ``400 "Invalid URL <internal message>"``.
    Two defects in one: a failure of the service was recorded as the
    caller's mistake, so it never reached error monitoring, and the text of
    an internal exception was published in the response body.
    ``JSONDecodeError`` and ``UnicodeDecodeError`` are ``ValueError``
    subclasses, which is how a corrupted cache entry got there.
    """

    def test_a_value_error_from_the_repository_is_not_turned_into_400(
        self, use_case, uow
    ):
        internal = ValueError(
            "could not convert string to float: internal-column-42"
        )
        uow.links.find_live_by_hash.side_effect = internal

        with pytest.raises(ValueError) as raised:
            use_case.execute(URL, _context(user_id="user-a"))

        # The very object the repository raised, neither replaced nor
        # wrapped. `assert not isinstance(raised.value, ValidationError)`
        # stood here and could never fail: ValidationError descends from
        # DomainError, not from ValueError, so pytest.raises(ValueError)
        # had already excluded it a line earlier.
        assert raised.value is internal

    def test_the_internal_message_is_not_rewritten_into_the_answer(
        self, use_case, uow
    ):
        """It stays an internal failure, so the 500 handler generalises it."""
        uow.links.find_live_by_hash.side_effect = ValueError("internal detail")

        with pytest.raises(ValueError) as raised:
            use_case.execute(URL, _context(user_id="user-a"))

        assert "Invalid URL" not in str(raised.value)

    def test_a_bad_url_is_still_a_validation_error(self, use_case):
        with pytest.raises(ValidationError):
            use_case.execute("not a url", _context(user_id="user-a"))
