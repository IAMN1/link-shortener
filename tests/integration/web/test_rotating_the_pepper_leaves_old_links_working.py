"""
What rotating ``SHORT_CODE_PEPPER`` costs the links already handed out.

Three places said it stopped them resolving: the troubleshooting tables of
both guides, and ``_COST_OF_REPLACING`` in ``security.py``, which words the
refusal ``generate-secrets`` prints when a file is already filled in. All
three read as "rotating this revokes the links you gave people", which is
a thing this service cannot do and should not be believed to.

The pepper is read in one place, ``Base64UrlCodeGenerator.generate``. A
link is resolved by looking its stored code up in ``urls``; nothing
recomputes a code from a URL to answer a redirect, and deduplication asks
the URL rather than the code. So a rotation changes what a URL *not yet
shortened* will be given, and nothing else.

Measured on a live stack before this was written: a code made under one
pepper answered ``302`` to the right destination from a process running
another, and offering the same URL again under the second pepper returned
the first link with ``Is new: False``.

Two applications rather than one with its pepper swapped: the container is
wired when the application is built, so a value replaced afterwards is not
the one the generator holds. They share a database file, which is what a
rotation actually looks like -- the same data, a new process, a different
secret.
"""

import pytest

from link_shortener.infrastructure.configs.app.testing import TestingConfig
from link_shortener.infrastructure.database.seed import seed_base_roles
from link_shortener.web.app_factory import create_app


BEFORE = "the-pepper-it-was-created-under"
AFTER = "an-entirely-different-pepper"
URL = "https://example.com/kept-across-a-rotation"


def _app(tmp_path, pepper, create_tables):
    """An application on the shared database, holding one pepper."""
    class Config(TestingConfig):
        pass

    Config.SHORT_CODE_SECRET_PEPPER = pepper
    Config.MAIL_ENABLED = False
    Config.DATABASE_URL = f"sqlite:///{tmp_path}/rotation.db"

    app = create_app(config=Config())
    if create_tables:
        with app.app_context():
            manager = app.container.get_db_manager()
            manager.create_tables()
            with manager.session() as session:
                seed_base_roles(session)
    return app


@pytest.fixture(scope="module")
def rotation(tmp_path_factory):
    """
    A link made under one pepper, and a second application under another.

    Returns:
        The short code, and the application that never saw the pepper it
        was made with.
    """
    tmp_path = tmp_path_factory.mktemp("pepper-rotation")

    before = _app(tmp_path, BEFORE, create_tables=True)
    with before.test_client() as client:
        made = client.post("/api/v1/shorten", json={"url": URL})
        assert made.status_code == 201, made.get_data(as_text=True)[:200]
        code = made.get_json()["short_code"]

    after = _app(tmp_path, AFTER, create_tables=False)
    return code, after


class TestTheCodeIsNotRecomputed:

    def test_the_two_peppers_really_do_differ_for_this_url(self, rotation, tmp_path_factory):
        """
        Otherwise the checks below would pass on identical codes.

        The generator is asked directly: what a fresh URL is given under
        each pepper has to differ, or the rotation under test is not one.
        """
        code, after = rotation
        generator = after.container.policy_component.get_code_generator()

        assert generator.generate(URL).value != code

    def test_the_old_code_still_resolves(self, rotation):
        """The redirect a person was handed goes on working."""
        code, after = rotation

        with after.test_client() as client:
            response = client.get(f"/{code}", follow_redirects=False)

        assert response.status_code == 302
        assert response.headers["Location"] == URL

    def test_the_api_still_finds_it(self, rotation):
        """And the route that reads a link by its code finds the same one."""
        code, after = rotation

        with after.test_client() as client:
            response = client.get(f"/api/v1/links/{code}")

        assert response.status_code == 200
        assert response.get_json()["original_url"] == URL

    def test_the_same_url_still_deduplicates_to_it(self, rotation):
        """
        Deduplication reads the URL, not a recomputed code.

        This is the half that would break first if anything did the
        arithmetic again on the way in: a rotation would strand the old
        row and hand out a second link for one URL.
        """
        code, after = rotation

        with after.test_client() as client:
            again = client.post("/api/v1/shorten", json={"url": URL})

        assert again.status_code == 200
        body = again.get_json()
        assert body["short_code"] == code
        assert body["is_new"] is False


class TestTheSentenceThatSaidOtherwise:

    def test_the_cli_no_longer_claims_the_codes_stop_working(self):
        """
        The refusal `generate-secrets` prints is worded from this table.

        Checked here beside the behaviour rather than in a file of its
        own: the sentence is only wrong because of what the tests above
        measure, and a reader who breaks one should be standing at the
        other.
        """
        from link_shortener.infrastructure.cli.commands.security import (
            _COST_OF_REPLACING,
        )

        cost = _COST_OF_REPLACING["SHORT_CODE_PEPPER"]

        assert "from resolving" not in cost, cost
        assert "keep theirs" in cost, cost
