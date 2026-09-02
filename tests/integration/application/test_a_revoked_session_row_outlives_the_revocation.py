"""
``clean-sessions`` leaves a revoked session alone until it expires, and
that is what keeps a replay detectable.

Read from outside it looks like a sweep that misses half its work: a run
that revoked eleven sessions leaves eleven rows behind, and
``maintenance clean-sessions`` reports "Deleted 0 expired refresh
sessions". Deleting them would be wrong.

A replay is recognised by finding the row the presented token names and
seeing it was already spent. With the row gone the same token names
nothing, which is exactly what an expired or forged one looks like -- so
an early sweep would turn every theft detectable inside the refresh
lifetime into an ordinary refusal, and take ``REFRESH_TOKEN_REPLAYED`` out
of the security journal with it.

Held here because the two live in different files and neither says the
other's name: the sweep is a repository method, the detection is in the
token service, and the thing that connects them is a row nobody deletes.
"""

from link_shortener.application.ports.logger.audit import AuditEvent
from tests.integration.conftest import csrf_headers
from tests.integration.web.middleware.test_authentication import (
    _register_and_get_tokens,
)


class TestTheSweepLeavesARevokedSessionInPlace:

    def test_signing_out_does_not_make_the_row_sweepable(self, app):
        from sqlalchemy import text

        client = app.test_client()
        access, _ = _register_and_get_tokens(client, "kept-row@example.com")
        client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {access}", **csrf_headers(client)},
        )

        with app.app_context():
            with app.container.get_db_manager().session() as session:
                revoked_rows = session.execute(
                    text(
                        "SELECT count(*) FROM refresh_sessions "
                        "WHERE revoked_at IS NOT NULL "
                        "AND expires_at > CURRENT_TIMESTAMP"
                    )
                ).scalar_one()
            swept = app.container.get_uow_factory()

        assert revoked_rows >= 1

        with app.app_context():
            with swept() as uow:
                deleted = uow.refresh_sessions.delete_expired()
                uow.commit()

        assert deleted == 0, "a revoked session was swept before it expired"


class TestAndThatIsWhatKeepsAReplayVisible:

    def test_a_replay_after_a_sweep_is_still_recorded(self, app, events):
        """
        The consequence, measured rather than argued -- and measured in
        the one order that shows it.

        A rotation alone leaves ``replaced_by`` set and ``revoked_at``
        empty, so a sweep of revoked rows would not touch it and this
        would pass whatever the sweep did. **Signing out** is what marks
        the whole chain revoked, the rows already rotated included, and
        those are the ones a token stolen mid-session names. Measured::

            after one rotation  A(replaced=True,  revoked=False)
            after logout        A(replaced=True,  revoked=True)

        So the order here is login, rotate, sign out, sweep, replay -- the
        order a schedule running after a working day produces, and the
        only one in which an early sweep costs the alarm.
        """
        client = app.test_client()
        _register_and_get_tokens(client, "kept-row-replay@example.com")

        stolen = client.get_cookie("refresh_token").value
        rotated = client.post("/api/v1/auth/refresh", headers=csrf_headers(client))
        assert rotated.status_code == 200, rotated.get_data(as_text=True)[:200]

        signed_out = client.post(
            "/api/v1/auth/logout", headers=csrf_headers(client)
        )
        assert signed_out.status_code == 200

        with app.app_context():
            with app.container.get_uow_factory()() as uow:
                uow.refresh_sessions.delete_expired()
                uow.commit()

        before = events(AuditEvent.REFRESH_TOKEN_REPLAYED.value)
        thief = app.test_client()
        replayed = thief.post(
            "/api/v1/auth/refresh", json={"refresh_token": stolen}
        )

        assert replayed.status_code == 401
        assert events(AuditEvent.REFRESH_TOKEN_REPLAYED.value) == before + 1
