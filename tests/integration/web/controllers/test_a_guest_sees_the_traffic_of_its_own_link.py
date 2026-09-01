"""
"Shown only to whoever made the link" was true of nobody for a guest link.

The landing page and the guide both say the click counters belong to the
maker. A guest link has no owner -- ``owner_id`` is null by construction --
so the check that withholds traffic from everybody but the owner withheld
it from the person who made it as firmly as from a stranger. Measured on a
live stack: the answer that *created* the link carried ``clicks: 0`` and
every look at it afterwards carried ``clicks: null``, for the same caller,
seconds apart.

What a guest has instead of an owner is the deletion token, which is what
``DELETE /api/v1/links/<code>`` already accepts as proof of having made the
link. So the same proof now answers the same question here.

It widens nothing, and the checks below say why in the only way that
counts. The token is signed with ``SECRET_KEY``; it names the row rather
than the code, so it proves this caller made *this* link; and a caller
holding somebody else's token, a forged one, or none at all is told
exactly what they were told before.
"""

import itertools

import pytest


def a_guest(app, address: str):
    """A client the service counts as a guest of its own."""
    client = app.test_client()
    client.environ_base["REMOTE_ADDR"] = address
    return client


def make(client, url: str):
    """One guest link, and the whole answer."""
    return client.post("/api/v1/shorten", json={"url": url})


_urls = itertools.count()


@pytest.fixture
def made(app):
    """
    A guest link, its code, and the token issued with it.

    A fresh URL each time: the token comes back once, with the answer that
    creates the link, and asking for a URL this service already holds is a
    deduplicated ``200`` carrying ``deletion_token: null``. Written with
    one URL, the second test in this file was handed that and measured
    nothing.
    """
    guest = a_guest(app, "192.0.2.210")
    url = f"https://example.com/guest-traffic/{next(_urls)}"
    answer = make(guest, url)
    assert answer.status_code == 201, answer.get_data(as_text=True)[:200]
    body = answer.get_json()
    return guest, body["short_code"], body["deletion_token"], url


class TestTheMakerOfAGuestLink:

    def test_is_shown_its_traffic(self, app, made):
        guest, code, token, _ = made

        seen = guest.get(
            f"/api/v1/links/{code}", headers={"X-Deletion-Token": token}
        )

        assert seen.status_code == 200
        assert seen.get_json()["clicks"] == 0

    def test_the_figure_follows_the_redirects(self, app, made):
        """
        A counter that is always zero would pass the check above.

        Celery is off under the test profile, so the click is counted on
        the request that redirected.
        """
        guest, code, token, _ = made
        guest.get(f"/{code}")
        guest.get(f"/{code}")

        seen = guest.get(
            f"/api/v1/links/{code}", headers={"X-Deletion-Token": token}
        )

        assert seen.get_json()["clicks"] == 2


class TestEverybodyElseIsToldWhatTheyWereBefore:

    def test_without_the_token(self, app, made):
        guest, code, _, _ = made

        seen = guest.get(f"/api/v1/links/{code}")

        assert seen.status_code == 200
        assert seen.get_json()["clicks"] is None
        assert seen.get_json()["owner_id"] is None

    def test_with_a_forged_one(self, app, made):
        guest, code, _, _ = made

        seen = guest.get(
            f"/api/v1/links/{code}",
            headers={"X-Deletion-Token": "not.a.real.token"},
        )

        assert seen.get_json()["clicks"] is None

    def test_with_somebody_elses(self, app, made):
        """
        The check that makes the token proof of *this* link.

        A token that opened any link would be a token worth stealing from
        a URL bar; this one names the row it was issued for.
        """
        guest, code, _, _ = made
        other = a_guest(app, "192.0.2.211")
        theirs = make(
            other, f"https://example.com/guest-traffic-other/{next(_urls)}"
        ).get_json()

        seen = guest.get(
            f"/api/v1/links/{code}",
            headers={"X-Deletion-Token": theirs["deletion_token"]},
        )

        assert seen.get_json()["clicks"] is None

    def test_a_stranger_holding_nothing_sees_the_link_itself(self, app, made):
        """
        What stays public stays public: the code still resolves.

        The endpoint is meant to turn a code into an address for anyone.
        Only the owner's identity and the traffic were ever withheld.
        """
        _, code, _, url = made
        stranger = a_guest(app, "192.0.2.212")

        seen = stranger.get(f"/api/v1/links/{code}")

        assert seen.status_code == 200
        assert seen.get_json()["original_url"] == url
        assert seen.get_json()["clicks"] is None


class TestTheDerivedFiguresFollowTheSameProof:
    """
    Both endpoints withhold from the same people, or neither does.

    That sentence is at the top of ``api_controller`` and it stopped being
    true when the basic endpoint began honouring the deletion token: the
    maker of a guest link was handed ``clicks``, ``created_at`` and
    ``last_accessed`` there and refused ``clicks_per_day`` next door --
    which is arithmetic on the three they already had. The extended
    endpoint takes the same proof now.
    """

    def test_the_maker_is_shown_the_derived_figures(self, app, made):
        guest, code, token, _ = made

        seen = guest.get(
            f"/api/v1/links/{code}/extended",
            headers={"X-Deletion-Token": token},
        )

        assert seen.status_code == 200, seen.get_data(as_text=True)[:200]
        assert seen.get_json()["clicks_per_day"] is not None

    def test_a_stranger_is_still_refused(self, app, made):
        """The half that keeps the proof worth presenting."""
        _, code, _, _ = made
        stranger = a_guest(app, "192.0.2.217")

        seen = stranger.get(f"/api/v1/links/{code}/extended")

        assert seen.status_code in (401, 403)

    def test_a_forged_token_is_refused(self, app, made):
        _, code, _, _ = made
        stranger = a_guest(app, "192.0.2.218")

        seen = stranger.get(
            f"/api/v1/links/{code}/extended",
            headers={"X-Deletion-Token": "not-a-token"},
        )

        assert seen.status_code in (401, 403)


class TestTheAnswerSaysWhatItVariesBy:
    """
    One URL, two bodies, and a header deciding which — so it must say so.

    ``PrivateCacheMiddleware`` makes this argument itself, for the two
    names it does add: "``/`` renders ``data-theme="dark"`` or nothing at
    all depending on a cookie, carries no ``Cache-Control``, and said it
    varied by ``Accept-Encoding`` alone. A shared cache had every right to
    hand one visitor's page to the next." ``X-Deletion-Token`` joined the
    answer after that list was written.

    It cannot be caught by the bodies alone, and the tests above look only
    at bodies. Measured before this: both answers came back
    ``Vary: Cookie, Accept-Language, Accept-Encoding`` and no
    ``Cache-Control`` — a guest is anonymous, so the middleware returns
    above its ``no-store`` branch — while one of them carried the counters.
    """

    def test_the_header_is_named_in_vary(self, app, made):
        """Named on both answers, since a cache stores whichever it saw."""
        guest, code, token, _ = made

        with_token = guest.get(
            f"/api/v1/links/{code}", headers={"X-Deletion-Token": token}
        )
        without = guest.get(f"/api/v1/links/{code}")

        assert "X-Deletion-Token" in with_token.headers.get("Vary", "")
        assert "X-Deletion-Token" in without.headers.get("Vary", "")

    def test_the_names_that_were_already_there_are_still_there(self, app, made):
        """
        Added to the list rather than put in place of it.

        The answer is translated, so ``Cookie`` and ``Accept-Language``
        decide it too, and dropping either would be the fault this fixes
        wearing a different name.
        """
        guest, code, _, _ = made

        varies = guest.get(f"/api/v1/links/{code}").headers.get("Vary", "")

        assert "Cookie" in varies
        assert "Accept-Language" in varies

    def test_the_answer_carrying_the_counters_is_not_stored(self, app, made):
        """
        The half that does not depend on a cache implementing ``Vary``.

        These counters belong to whoever made the link, which is what
        ``no-store`` marks everywhere else in this service.
        """
        guest, code, token, _ = made

        answered = guest.get(
            f"/api/v1/links/{code}", headers={"X-Deletion-Token": token}
        )

        assert answered.get_json()["clicks"] is not None
        assert answered.headers.get("Cache-Control") == "no-store"

    def test_the_public_answer_is_still_cacheable(self, app, made):
        """
        And the half that keeps the fix from costing the caching.

        An answer with no counters in it is the same bytes for everybody,
        and marking it unstorable would spend what the cache is for.
        """
        _, code, _, _ = made
        stranger = a_guest(app, "192.0.2.216")

        answered = stranger.get(f"/api/v1/links/{code}")

        assert answered.get_json()["clicks"] is None
        assert answered.headers.get("Cache-Control") != "no-store"
