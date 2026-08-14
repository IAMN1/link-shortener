"""
What reaches the log when the URL that was submitted holds a password.

Three lines used to write unchecked input: the "Starting short link
creation" record, the wrap of ``urlparse``'s own error text, and the
per-item warning of a batch. Each ran before -- or instead of -- the check
that refuses credentials, so an address the service was about to reject
had already been written down whole.

The assertions here look at every argument of every logger call rather
than at one named field. A test that pins ``url=`` passes the moment the
secret moves to ``error=``, which is exactly how it moved the first time.
"""

import traceback
from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock

import pytest

from link_shortener.application.context import RequestContext
from link_shortener.application.use_cases.batch.grouper import UrlGrouper
from link_shortener.application.use_cases.links.create_short_link import (
    CreateShortLinkUseCase,
)
from link_shortener.application.use_cases.links.redirect_link import (
    RedirectLinkUseCase,
)
from link_shortener.domain import (
    Link, OriginalUrl, ShortCode, UrlHash, ValidationError
)


SECRET = "pw1"
"""Short, and placed early, because that is the hard case.

A long distinctive password sitting past character 30 is hidden by any
truncation, so a line that writes ``url[:25]`` -- unchecked input, just
less of it -- passes a test built on one. With a 19-character secret at
offset 14, ``url_head=url[:25]`` passes everything else while putting
``https://a:hunter2@example`` in application.log. Three
characters after ``https://a:`` cannot hide behind any slice worth
taking.
"""

WITH_CREDENTIALS = f"https://a:{SECRET}@example.com/x"
"""Refused by ``_validate_no_credentials``, with a clean message."""

BREAKS_NFKC = f"https://a:{SECRET}@exa℀mple.com/"
"""Refused by ``urlparse`` itself, whose error text quotes the netloc.

U+2100 (ACCOUNT OF) is one of the code points CPython's NFKC check
refuses in an authority, so this is the input whose error text carries the
password into ``error.log`` and into the 400 body.
"""


def _recorded(mock_logger) -> str:
    """
    Everything the code under test said to its logger, as one string.

    Args:
        mock_logger: The logger passed in, whose ``bind`` returns the
            object the use case actually writes to.

    Returns:
        Repr of every call, on both the logger and its bound child.
    """
    bound = mock_logger.bind.return_value
    return repr(mock_logger.method_calls) + repr(bound.method_calls)


@pytest.fixture
def logger():
    """A logger that remembers, and whose ``bind`` remembers too."""
    log = Mock()
    log.bind.return_value = Mock()
    return log


@pytest.fixture
def use_case(logger):
    """The creator, with every collaborator stubbed out."""
    uow = Mock()
    factory = Mock(return_value=MagicMock())
    factory.return_value.__enter__ = Mock(return_value=uow)
    factory.return_value.__exit__ = Mock(return_value=False)

    hash_calculator = Mock()
    hash_calculator.calculate.return_value = UrlHash("a" * 64)

    audit = Mock()
    audit.bind.return_value = Mock()

    return CreateShortLinkUseCase(
        uow_factory=factory,
        cache=Mock(),
        stats_cache=Mock(),
        hash_calculator=hash_calculator,
        code_generator=Mock(),
        base_url="https://short.link",
        logger=logger,
        audit_logger=audit,
        allowed_schemes=["http", "https"],
        max_url_length=2048,
        allow_internal_targets=False,
        guest_link_limit=10,
        guest_link_window_days=1,
        default_guest_ttl_seconds=604800,
        max_ttl_seconds=10 * 365 * 24 * 3600,
        max_collision_attempts=3,
    )


@pytest.fixture
def context():
    """A guest request, the path with no account behind it."""
    return RequestContext(
        request_id="req-1",
        remote_addr="127.0.0.1",
        user_agent="Mozilla/5.0",
        request_path="/api/v1/shorten",
        request_method="POST",
        current_user=None,
    )


class TestCreatingOneLink:
    """The single-link path, where the first record precedes every check."""

    def test_a_refused_address_leaves_no_password_behind(
        self, use_case, logger, context
    ):
        """The address is refused nine lines after it is logged."""
        with pytest.raises(ValidationError):
            use_case.execute(WITH_CREDENTIALS, context=context)

        assert SECRET not in _recorded(logger)

    def test_an_address_urlparse_itself_refuses_leaves_none_either(
        self, use_case, logger, context
    ):
        """The path where the secret came back inside someone else's text.

        ``urlparse`` raises before ``_validate_no_credentials`` is ever
        reached, so the clean message that check produces never happens
        here: whatever this branch says is what gets written.
        """
        with pytest.raises(ValidationError) as caught:
            use_case.execute(BREAKS_NFKC, context=context)

        assert SECRET not in str(caught.value)
        assert SECRET not in _recorded(logger)

    def test_masking_the_url_here_would_not_be_enough(
        self, use_case, logger, context
    ):
        """The rule is that unchecked input is not written, not that it is
        written more carefully.

        ``mask_url`` removes userinfo and deliberately leaves query
        strings alone -- so a line reading ``url=mask_url(url)`` passes
        every credential test in this file while writing an OAuth token
        into application.log. This input has no credentials at all: it is
        refused for its scheme, and its secret is in the query.
        """
        with pytest.raises(ValidationError):
            use_case.execute(
                f"ftp://idp.example/cb?access_token={SECRET}", context=context
            )

        assert SECRET not in _recorded(logger)

    def test_the_record_still_says_a_creation_started(
        self, use_case, logger, context
    ):
        """Dropping the field must not drop the line.

        Without this, deleting the record altogether would pass the two
        tests above -- and the trail would lose the one mark that says
        work began at all.
        """
        with pytest.raises(ValidationError):
            use_case.execute(WITH_CREDENTIALS, context=context)

        bound = logger.bind.return_value
        started = [
            call for call in bound.method_calls
            if call.args and call.args[0] == "Starting short link creation"
        ]
        assert len(started) == 1
        assert started[0].kwargs["url_length"] == len(WITH_CREDENTIALS)


class TestTheTracebackCarriesNothingEither:
    """``from None`` is load-bearing, and nothing else was watching it."""

    def test_no_chained_exception_holds_the_quoted_authority(self):
        """A clean message is not enough on its own.

        Chaining the original ``ValueError`` onto the ``ValidationError``
        keeps its text -- which quotes the whole netloc -- on the raised
        object. Five calls in ``src/`` are ``log.exception``, and a 500
        handler formats tracebacks too, so anything that prints one puts
        the password back into the file the message just kept it out of.

        ``from None`` does not detach ``__context__`` -- Python keeps it
        and sets ``__suppress_context__``, which is what stops the
        traceback machinery from printing it. So that flag is the thing to
        assert; ``__cause__`` stays empty because nothing was chained on
        purpose either.
        """
        with pytest.raises(ValidationError) as caught:
            OriginalUrl(BREAKS_NFKC)

        error = caught.value
        assert error.__cause__ is None
        assert error.__suppress_context__ is True

    def test_a_formatted_traceback_has_no_password_in_it(self):
        """Asserted on the rendered text, which is what reaches a file.

        Not on the word "NFKC": the traceback quotes the source lines it
        walks through, and the name of the input constant contains it.
        The phrase below belongs to CPython's message and appears nowhere
        else.
        """
        try:
            OriginalUrl(BREAKS_NFKC)
        except ValidationError as exc:
            rendered = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )
        else:
            pytest.fail("the input must be refused")

        assert SECRET not in rendered
        assert "contains invalid characters" not in rendered
        assert "During handling of the above exception" not in rendered


class TestServingARedirect:
    """The path where the URL is trusted and therefore never checked."""

    @pytest.fixture
    def redirect(self, logger):
        """A redirect use case whose repository holds a legacy row."""
        stored = Link(
            id="link-1",
            url_hash=UrlHash("d" * 64),
            short_code=ShortCode("abc123"),
            original_url=OriginalUrl.from_storage(
                f"https://a:{SECRET}@example.com/legacy"
            ),
            created_at=datetime.now(timezone.utc),
        )

        uow = Mock()
        uow.links.find_by_code.return_value = stored
        factory = Mock(return_value=MagicMock())
        factory.return_value.__enter__ = Mock(return_value=uow)
        factory.return_value.__exit__ = Mock(return_value=False)

        audit = Mock()
        audit.bind.return_value = Mock()

        link_cache = Mock()
        link_cache.get_by_code.return_value = None
        redirect_cache = Mock()
        redirect_cache.get_redirect.return_value = None

        return RedirectLinkUseCase(
            uow_factory=factory,
            link_cache=link_cache,
            redirect_cache=redirect_cache,
            logger=logger,
            audit_logger=audit,
            task_queue=Mock(),
        )

    def test_a_stored_url_is_not_written_to_the_log(self, redirect, logger):
        """``from_storage`` skips the credentials check on purpose.

        Rows admitted under older rules have to stay readable, so a row
        holding a password is a row this path serves normally -- on every
        cache miss, which is the ordinary case after a restart. The audit
        line records the destination through ``mask_url``; the plain log
        line does not record it at all.
        """
        result = redirect.execute("abc123", RequestContext(request_id="t"))

        assert result == f"https://a:{SECRET}@example.com/legacy"
        assert SECRET not in _recorded(logger)


class TestGroupingABatch:
    """The batch path, where a refused URL is a per-item outcome."""

    @pytest.fixture
    def grouper(self, logger):
        """The grouper, with the domain's real hash calculator stubbed."""
        hash_calculator = Mock()
        hash_calculator.calculate.return_value = UrlHash("c" * 64)
        return UrlGrouper(
            allowed_schemes=["http", "https"],
            max_url_length=2048,
            allow_internal_targets=False,
            hash_calculator=hash_calculator,
            logger=logger,
        )

    def test_neither_refused_url_reaches_the_log(self, grouper, logger):
        """One item per refusal, and a batch may be all refusals."""
        grouper.group([WITH_CREDENTIALS, BREAKS_NFKC])

        assert SECRET not in _recorded(logger)

    def test_the_warning_still_names_which_item_failed(self, grouper, logger):
        """The line has to stay findable against the response.

        The caller is told which URL failed -- ``BatchItemResponse`` echoes
        it back -- so the log needs the key that ties the two together, not
        the address.
        """
        groups = grouper.group(["https://example.com/ok", WITH_CREDENTIALS])

        warnings = [
            call for call in logger.method_calls
            if call.args and call.args[0] == "Invalid URL in batch"
        ]
        assert len(warnings) == 1
        assert warnings[0].kwargs["item"] == "invalid_0"
        assert "invalid_0" in groups

    def test_what_goes_back_to_the_caller_carries_no_secret_either(
        self, grouper
    ):
        """The per-item error is a response field, not only a log field.

        The URL beside it is the caller's own, so echoing that reveals
        nothing new -- but ``urlparse`` quotes the netloc in its message,
        and a batch response travels further than the request did.
        """
        groups = grouper.group([BREAKS_NFKC])

        assert SECRET not in groups["invalid_0"]["error"]
