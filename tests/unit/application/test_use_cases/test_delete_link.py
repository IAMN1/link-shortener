from unittest.mock import Mock, MagicMock

from link_shortener.application.context import RequestContext
from link_shortener.application.use_cases.links.delete_link import DeleteLinkUseCase
from link_shortener.application.dtos.current_user_info import CurrentUserInfo
from link_shortener.domain import (
    DomainError, Link, OriginalUrl, OwnerID, PermissionDeniedError,
    ShortCode, SystemPermissions, UrlHash,
)
import pytest


@pytest.fixture
def mock_uow_factory():
    uow = Mock()
    factory = Mock(return_value=MagicMock())
    factory.return_value.__enter__ = Mock(return_value=uow)
    factory.return_value.__exit__ = Mock(return_value=False)
    return factory, uow


@pytest.fixture
def mock_cache():
    return Mock()


@pytest.fixture
def mock_redirect_cache():
    return Mock()


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
def context():
    return RequestContext(
        request_id="req-1",
        remote_addr="127.0.0.1",
        user_agent="Mozilla/5.0",
        request_path="/api/v1/links/abc123",
        request_method="DELETE",
    )


@pytest.fixture
def sample_link():
    return Link.create(
        url_hash=UrlHash("a" * 64),
        short_code=ShortCode("abc123"),
        original_url=OriginalUrl("https://example.com"),
    )


@pytest.fixture
def use_case(mock_uow_factory, mock_cache, mock_redirect_cache, mock_logger, mock_audit_logger):
    factory, _ = mock_uow_factory
    return DeleteLinkUseCase(
        uow_factory=factory,
        cache=mock_cache,
        stats_cache=mock_cache,
        redirect_cache=mock_redirect_cache,
        logger=mock_logger,
        audit_logger=mock_audit_logger,
        authorization_service=Mock(),
    )


class TestDeleteLinkUseCase:
    """Tests for the DeleteLinkUseCase."""

    def test_delete_existing_link(
        self, use_case, mock_uow_factory, mock_cache, mock_redirect_cache, sample_link, context
    ):
        factory, uow = mock_uow_factory
        uow.links.find_by_code.return_value = sample_link
        uow.links.delete.return_value = True

        result = use_case.execute("abc123", context, enforce_ownership=False)

        assert result is True
        uow.links.delete.assert_called_once()
        uow.commit.assert_called_once()
        # The entity, not the code: only it names the deduplication key.
        mock_cache.delete.assert_called_once_with(sample_link)
        mock_redirect_cache.delete_redirect.assert_called_once()

    def test_delete_nonexistent_link(
        self, use_case, mock_uow_factory, mock_cache, mock_redirect_cache, context
    ):
        factory, uow = mock_uow_factory
        uow.links.find_by_code.return_value = None

        result = use_case.execute("abc123", context, enforce_ownership=False)

        assert result is False
        uow.links.delete.assert_not_called()
        # Nothing is deleted from the table, and the entity-keyed
        # invalidation cannot run without an entity.
        mock_cache.delete.assert_not_called()

    def test_a_cache_entry_that_outlived_its_row_is_still_cleared(
        self, use_case, mock_uow_factory, mock_cache, mock_redirect_cache, context
    ):
        """
        The answer stays 404, but the code-keyed entries go.

        An entry surviving its row is the state a second DELETE is issued to
        clear: every API surface calls the link deleted while the redirect
        keeps serving it for the rest of CACHE_LINK_TTL. Returning early
        left no command in the service able to touch it.
        """
        factory, uow = mock_uow_factory
        uow.links.find_by_code.return_value = None

        use_case.execute("abc123", context, enforce_ownership=False)

        mock_cache.delete_by_code.assert_called_once()
        mock_redirect_cache.delete_redirect.assert_called_once()

    def test_cache_invalidated_after_delete(
        self, use_case, mock_uow_factory, mock_cache, mock_redirect_cache, sample_link, context
    ):
        factory, uow = mock_uow_factory
        uow.links.find_by_code.return_value = sample_link
        uow.links.delete.return_value = True

        use_case.execute("abc123", context, enforce_ownership=False)

        mock_cache.delete.assert_called_once()
        mock_redirect_cache.delete_redirect.assert_called_once()

    def test_invalid_short_code_returns_false(
        self, use_case, mock_uow_factory, mock_cache, mock_redirect_cache, context
    ):
        result = use_case.execute("", context, enforce_ownership=False)

        assert result is False
        mock_cache.delete.assert_not_called()
        mock_redirect_cache.delete_redirect.assert_not_called()

    def test_delete_fails_returns_false(
        self, use_case, mock_uow_factory, mock_cache, mock_redirect_cache, sample_link, context
    ):
        factory, uow = mock_uow_factory
        uow.links.find_by_code.return_value = sample_link
        uow.links.delete.return_value = False

        result = use_case.execute("abc123", context, enforce_ownership=False)

        assert result is False
        uow.commit.assert_not_called()
        mock_cache.delete.assert_not_called()
        mock_redirect_cache.delete_redirect.assert_not_called()


class TestWhoMayDeleteWhichLink:
    """
    The branch every test above walks past.

    All of them pass ``enforce_ownership=False``, which is the CLI's call
    and the one path that skips ``_require_may_delete`` entirely — so the
    ownership decision, the only authorization this use case makes, was
    reached by no unit test at all. Measured: turning
    ``owner_id is not None and owner_id == requester.id`` into an ``or``
    left the unit suite green, and that flip hands a holder of
    ``link:delete_own`` anybody's link.

    The permission asked for is what these check, not the answer: the
    answer is the authorization service's, and it is a double here. What
    the use case decides is *which* permission the caller needs, and it
    decides it from the row it just read.
    """

    def _owned_by(self, owner_id):
        return Link.create(
            url_hash=UrlHash("b" * 64),
            short_code=ShortCode("abc123"),
            original_url=OriginalUrl("https://example.com"),
            owner=OwnerID(owner_id),
        )

    def _signed_in_as(self, uow, user_id):
        requester = Mock()
        requester.id = user_id
        uow.users.find_by_id.return_value = requester
        return RequestContext(
            request_id="req-1",
            remote_addr="127.0.0.1",
            current_user=CurrentUserInfo(
                id=user_id, email="who@example.com", roles=["user"],
                is_active=True,
            ),
        )

    def test_the_owner_is_asked_for_delete_own(
        self, use_case, mock_uow_factory
    ):
        factory, uow = mock_uow_factory
        uow.links.find_by_code.return_value = self._owned_by("user-1")
        uow.links.delete.return_value = True
        context = self._signed_in_as(uow, "user-1")
        use_case.authorization_service.is_allowed.return_value = True

        assert use_case.execute(
            "abc123", context, enforce_ownership=True
        ) is True

        _, asked = use_case.authorization_service.is_allowed.call_args[0]
        assert asked == SystemPermissions.LINK_DELETE_OWN.value

    def test_a_stranger_is_asked_for_delete_any(
        self, use_case, mock_uow_factory
    ):
        """The flip this class exists for: somebody else's link is not
        the caller's own, and asking for ``delete_own`` there is the whole
        defect."""
        factory, uow = mock_uow_factory
        uow.links.find_by_code.return_value = self._owned_by("somebody-else")
        uow.links.delete.return_value = True
        context = self._signed_in_as(uow, "user-1")
        use_case.authorization_service.is_allowed.return_value = True

        use_case.execute("abc123", context, enforce_ownership=True)

        _, asked = use_case.authorization_service.is_allowed.call_args[0]
        assert asked == SystemPermissions.LINK_DELETE_ANY.value

    def test_a_guest_link_is_nobody_s_own(self, use_case, mock_uow_factory):
        """``None == None`` must not read as ownership: a link with no
        owner belongs to no account, and its creator proves themselves
        with a token instead."""
        factory, uow = mock_uow_factory
        uow.links.find_by_code.return_value = Link.create(
            url_hash=UrlHash("c" * 64),
            short_code=ShortCode("abc123"),
            original_url=OriginalUrl("https://example.com"),
        )
        uow.links.delete.return_value = True
        context = self._signed_in_as(uow, "user-1")
        use_case.authorization_service.is_allowed.return_value = True

        use_case.execute("abc123", context, enforce_ownership=True)

        _, asked = use_case.authorization_service.is_allowed.call_args[0]
        assert asked == SystemPermissions.LINK_DELETE_ANY.value

    def test_a_refusal_names_the_permission_it_wanted(
        self, use_case, mock_uow_factory
    ):
        """What the error handler writes into the audit journal."""
        factory, uow = mock_uow_factory
        uow.links.find_by_code.return_value = self._owned_by("somebody-else")
        context = self._signed_in_as(uow, "user-1")
        use_case.authorization_service.is_allowed.return_value = False

        with pytest.raises(PermissionDeniedError) as refusal:
            use_case.execute("abc123", context, enforce_ownership=True)

        assert refusal.value.required == (
            SystemPermissions.LINK_DELETE_ANY.value,
        )
        uow.links.delete.assert_not_called()

    def test_an_anonymous_caller_is_unauthenticated_rather_than_forbidden(
        self, use_case, mock_uow_factory, context
    ):
        """A client can tell "sign in" from "signing in will not help"."""
        factory, uow = mock_uow_factory
        uow.links.find_by_code.return_value = self._owned_by("user-1")

        with pytest.raises(DomainError) as refusal:
            use_case.execute("abc123", context, enforce_ownership=True)

        assert refusal.value.code == "UNAUTHENTICATED"
        uow.links.delete.assert_not_called()

    def test_a_matching_deletion_token_skips_the_question(
        self, use_case, mock_uow_factory, context
    ):
        """The guest's own handle: the row was judged by its id, so the
        authorization service is not asked at all."""
        factory, uow = mock_uow_factory
        link = self._owned_by("somebody-else")
        uow.links.find_by_code.return_value = link
        uow.links.delete.return_value = True

        assert use_case.execute(
            "abc123", context,
            enforce_ownership=True, authorized_link_id=link.id,
        ) is True

        use_case.authorization_service.is_allowed.assert_not_called()
