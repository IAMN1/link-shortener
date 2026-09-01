"""
What the guest allowance counts, held against what the documents say it
counts.

``configuration.md`` used to describe ``GUEST_LINK_LIMIT`` as "links per
window for one address", and the landing page says "10 links a day".
Neither said what the window is counted *over*, and the answer decides
whether the setting is a rate limit or a storage bound. It is the second:
the query is

    count(*) WHERE owner_id IS NULL
             AND guest_identifier = :id
             AND created_at >= cutoff

so a link that is deleted stops being counted. Measured on a live stack: a
guest refused at ten was answered ``201`` immediately after removing one
with its deletion token, and the cycle repeated without limit.

Left as it is, and documented instead. For a guest who does not delete --
which is nearly all of them -- "ten a day" is exactly true, and the
sentence on the landing page has one line to say it in. What the operator
choosing the number needs is the rule, and that belongs where an operator
reads, which is why ``architecture.md`` and ``configuration.md`` now carry
it.

Held here so the sentence and the behaviour cannot part: whichever is
changed next, the other has to be looked at.
"""

import pytest

from tests.integration.conftest import csrf_headers


def make(client, n: int):
    """Ask for one guest link, and hand back the whole answer."""
    return client.post(
        "/api/v1/shorten", json={"url": f"https://example.com/quota/{n}"}
    )


def a_guest(app, address: str):
    """
    A client the service will count as its own guest.

    The allowance is per address, so two tests sharing one are one guest
    between them: written without this, the second test here found the
    first had spent the allowance, read ``deletion_token`` off a ``429``
    and got ``None``. The same shape as the trap the live runs met, where
    every agent on the machine reached the container as one gateway
    address.
    """
    client = app.test_client()
    client.environ_base["REMOTE_ADDR"] = address
    return client


class TestTheAllowanceBoundsWhatIsKept:

    @pytest.fixture
    def limit(self, app):
        return app.config["GUEST_LINK_LIMIT"]

    def test_a_guest_is_refused_at_the_limit(self, app, limit):
        with a_guest(app, "192.0.2.170") as guest:
            answers = [make(guest, n).status_code for n in range(limit + 1)]

        assert answers[:limit] == [201] * limit
        assert answers[limit] == 429

    def test_deleting_one_frees_its_place_at_once(self, app, limit):
        """
        The half neither document mentioned.

        This is what makes the setting a bound on storage rather than on
        the rate of asking, and it is why the throttle exists separately.
        """
        with a_guest(app, "192.0.2.171") as guest:
            made = [make(guest, n) for n in range(limit)]
            assert make(guest, limit).status_code == 429

            first = made[0].get_json()
            removed = guest.delete(
                f"/api/v1/links/{first['short_code']}",
                headers={
                    "X-Deletion-Token": first["deletion_token"],
                    **csrf_headers(guest),
                },
            )
            assert removed.status_code in (200, 204), removed.get_data(as_text=True)[:200]

            assert make(guest, limit + 1).status_code == 201

    def test_the_documents_say_so(self):
        """
        The sentences this file exists beside.

        Quoted rather than paraphrased: what went wrong was that both
        documents described the setting without saying what it counts, and
        a paraphrase here could drift the same way.
        """
        from pathlib import Path

        root = Path(__file__).resolve().parents[3]
        architecture = (root / "docs/architecture.md").read_text(encoding="utf-8")
        configuration = (root / "docs/configuration.md").read_text(encoding="utf-8")

        assert "deleting a link\n  frees its place at once" in architecture
        assert "a deletion frees its place at once" in configuration
