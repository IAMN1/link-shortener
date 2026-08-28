"""
Tests for the limits that per-owner deduplication newly exposes.

While a URL could only ever have one link, a code supply of five per URL and
a quota charged before deduplication were both unreachable. Deduplication is
now per owner and skips expired links, so the same URL legitimately needs
many codes, and a caller can legitimately ask for a link they already have.
"""

import uuid


from tests.integration.conftest import (
    auth_headers, csrf_headers, register_and_login
)


def _url():
    """Return a URL nothing else in the session has shortened."""
    return f"https://example.com/{uuid.uuid4().hex}"


def _shorten(client, url, ip="203.0.113.90", token=None):
    """Shorten one URL as a guest or as an account."""
    return client.post(
        "/api/v1/shorten",
        json={"url": url},
        headers=csrf_headers(client, auth_headers(token)),
        environ_base={"REMOTE_ADDR": ip},
    )


class TestTheCodeSupplyIsNotFive:
    """
    Codes are derived from the URL, so the deterministic ladder is finite.

    ``generate_unique`` is a pure function of the URL and the attempt
    number, so a URL has exactly as many codes as there are attempts --
    ``MAX_COLLISION_ATTEMPTS``, five by default, and the same five for the
    lifetime of the service. With one link per owner, a sixth caller would
    get a 500 that no retry clears, and the URL would become unshortenable
    for everybody.
    """

    def test_eight_owners_can_all_shorten_the_same_url(self, app):
        url = _url()
        codes = []

        for index in range(8):
            client = app.test_client()
            token = register_and_login(
                client, email=f"supply-{index}-{uuid.uuid4().hex}@x.io"
            )
            response = _shorten(client, url, token=token)
            assert response.status_code == 201, response.get_json()
            codes.append(response.get_json()["short_code"])

        assert len(set(codes)) == len(codes), f"codes collided: {codes}"

    def test_every_issued_code_resolves(self, app):
        url = _url()
        client = app.test_client()

        codes = []
        for index in range(7):
            owner = app.test_client()
            token = register_and_login(
                owner, email=f"resolve-{index}-{uuid.uuid4().hex}@x.io"
            )
            codes.append(_shorten(owner, url, token=token).get_json()["short_code"])

        for code in codes:
            assert client.get(f"/{code}").status_code == 302


class TestTheQuotaIsChargedForCreationsOnly:
    """
    Being handed a link that already exists creates nothing.

    The single-link path has to look before it counts: counting first
    refuses a guest who has spent their allowance a URL they shortened
    themselves, while the batch endpoint, asked the same question, answers
    with the very same link.
    """

    def test_a_spent_guest_is_refused_a_genuinely_new_url(self, app):
        """
        The other half of the rule, and the one that must keep working.

        Named for what it does: every call here asks for a fresh ``_url()``,
        so nothing is asked for twice. A name promising the reuse would
        describe a path this body never takes -- that reuse is checked by
        ``test_repeating_an_existing_url_is_free`` below.
        """
        ip = "203.0.113.91"
        client = app.test_client()
        limit = app.config["GUEST_LINK_LIMIT"]

        for _ in range(limit):
            assert _shorten(client, _url(), ip=ip).status_code == 201

        assert _shorten(client, _url(), ip=ip).status_code == 429

    def test_repeating_an_existing_url_is_free(self, app):
        ip = "203.0.113.92"
        client = app.test_client()
        limit = app.config["GUEST_LINK_LIMIT"]

        url = _url()
        first = _shorten(client, url, ip=ip).get_json()["short_code"]
        for _ in range(limit - 1):
            _shorten(client, _url(), ip=ip)

        repeat = _shorten(client, url, ip=ip)

        assert repeat.status_code == 200
        assert repeat.get_json()["short_code"] == first
        assert repeat.get_json()["is_new"] is False


class TestOnlyGuestsAreCharged:
    """
    A caller with no address is not a guest with an odd one.

    The CLI builds a context with neither a user nor an address. Treating it
    as a guest gave its links a seven-day expiry nobody asked for and
    counted them against a quota, and -- because owned links carry a NULL
    guest identifier too -- ten links from any registered user were enough
    to report that quota as spent.
    """

    def test_a_context_without_an_address_is_not_rationed(self, app):
        from link_shortener.application.context import RequestContext

        with app.app_context():
            use_case = app.container.get_create_short_link_use_case()
            context = RequestContext(request_id="cli-test")

            for _ in range(app.config["GUEST_LINK_LIMIT"] + 3):
                result = use_case.execute(_url(), context)

            assert result.is_new is True

    def test_a_context_without_an_address_gets_no_guest_expiry(self, app):
        from link_shortener.application.context import RequestContext

        with app.app_context():
            use_case = app.container.get_create_short_link_use_case()
            result = use_case.execute(
                _url(), RequestContext(request_id="cli-test")
            )

        assert result.expires_at is None

    def test_owned_links_are_not_counted_against_a_guest(self, app):
        """Owned rows carry a NULL guest identifier; they are nobody's."""
        from link_shortener.infrastructure.database.repositories.sqlalchemy_link_repository import (
            SQLAlchemyLinkRepository,
        )

        def anonymous_count():
            with app.app_context():
                with app.container.get_db_manager().session() as session:
                    repo = SQLAlchemyLinkRepository(session)
                    return repo.count_guest_links_by_identifier(None, 1)

        before = anonymous_count()

        client = app.test_client()
        token = register_and_login(client, email=f"count-{uuid.uuid4().hex}@x.io")
        for _ in range(3):
            _shorten(client, _url(), token=token)

        # Owned links carry a NULL guest identifier too. Counted here, ten
        # of anyone's links would report the guest quota of an address-less
        # caller as spent.
        assert anonymous_count() == before
