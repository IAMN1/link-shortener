"""
Which sweeps leave a record, and which deliberately do not.

``AuditEvent`` is built on one rule -- "an act that changes who may do
what leaves a record" -- and ``UNVERIFIED_ACCOUNTS_SWEPT`` was added to it
after a measurement: the journal stood at 111 records before and 111 after
a run that deleted an account, so "an account is gone" was on the record
through one door and off it through the other.

Three more doors were in that state. Measured on a live stack, ``audit.log``
moved by zero lines across each of::

    flask maintenance clean-expired
    flask maintenance roll-up-security-events
    flask maintenance normalize-emails --apply

* **Links.** ``URL_DELETED`` records an operator removing one link; the
  sweep removed many and said nothing. The same asymmetry, about links
  instead of accounts.
* **The security history.** This is the one act in the service that takes
  rows *out of this journal*, and it left none in it. NIST SP 800-53 AU-9
  asks precisely for that: a trail that can be pruned without the pruning
  appearing in it protects nothing from the people who can prune it.
* **Addresses.** An address is how an account is identified and how it
  recovers a password, so rewriting one changes who may act as it.

What stays out, and why, is held below as firmly as what goes in. A record
per scheduled run would bury the runs that mattered, and a journal that
records sweeps of dead rows records nothing an investigator asks about.
"""

from link_shortener.application import RequestContext
from link_shortener.application.ports.logger.audit import AuditEvent


class TestASweepThatRemovedLinks:

    def test_it_is_recorded(self, app, events):
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import text

        # Its own address: the guest allowance is per address, and a test
        # that spends the shared one leaves later tests counting on it to
        # fail in a full run and pass alone.
        guest = app.test_client()
        guest.environ_base["REMOTE_ADDR"] = "192.0.2.190"
        made = guest.post(
            "/api/v1/shorten",
            json={"url": "https://example.com/swept-away", "ttl_seconds": 60},
        )
        assert made.status_code == 201, made.get_data(as_text=True)[:200]
        code = made.get_json()["short_code"]

        with app.app_context():
            with app.container.get_db_manager().session() as session:
                session.execute(
                    text("UPDATE urls SET expires_at = :past WHERE short_code = :c"),
                    {
                        "past": datetime.now(timezone.utc) - timedelta(days=2),
                        "c": code,
                    },
                )
                session.commit()

            before = events(AuditEvent.EXPIRED_LINKS_SWEPT.value)
            swept = app.container.get_clean_expired_links_use_case().execute(
                RequestContext(request_id="sweep-test")
            )

        assert swept >= 1
        assert events(AuditEvent.EXPIRED_LINKS_SWEPT.value) == before + 1

    def test_a_sweep_that_removed_nothing_is_not(self, app, events):
        """
        A schedule over a quiet service must not fill the journal.

        Written down at ``clean_unverified_accounts`` and held here: the
        records that matter would sit among a line per run otherwise.
        """
        with app.app_context():
            app.container.get_clean_expired_links_use_case().execute(
                RequestContext(request_id="sweep-test")
            )
            before = events(AuditEvent.EXPIRED_LINKS_SWEPT.value)
            app.container.get_clean_expired_links_use_case().execute(
                RequestContext(request_id="sweep-test")
            )

        assert events(AuditEvent.EXPIRED_LINKS_SWEPT.value) == before


class TestASweepOfTheJournalsOwnRows:

    def test_it_is_recorded_in_the_journal_it_swept(self, app, events):
        """
        The record goes into the thing being pruned. That is the point.

        AU-9 is about the trail surviving the people who can act on it,
        and a sweep recorded somewhere else is a sweep whoever ran it can
        remove separately.
        """
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import text

        with app.app_context():
            with app.container.get_db_manager().session() as session:
                session.execute(
                    text(
                        "INSERT INTO security_events "
                        "(id, event_type, occurred_at) "
                        "VALUES (:i, :t, :when)"
                    ),
                    {
                        "i": "sweep-fixture-1",
                        "t": "LOGIN_FAILED",
                        "when": datetime.now(timezone.utc) - timedelta(days=3),
                    },
                )
                session.commit()

            before = events(AuditEvent.SECURITY_HISTORY_SWEPT.value)
            folded, _ = app.container.get_roll_up_security_events_use_case().execute(
                RequestContext(request_id="sweep-test")
            )

        assert folded >= 1, "nothing was folded, so nothing is being tested"
        assert events(AuditEvent.SECURITY_HISTORY_SWEPT.value) == before + 1

    def test_a_run_that_moved_nothing_is_not_recorded(self, app, events):
        with app.app_context():
            app.container.get_roll_up_security_events_use_case().execute(
                RequestContext(request_id="sweep-test")
            )
            before = events(AuditEvent.SECURITY_HISTORY_SWEPT.value)
            app.container.get_roll_up_security_events_use_case().execute(
                RequestContext(request_id="sweep-test")
            )

        assert events(AuditEvent.SECURITY_HISTORY_SWEPT.value) == before
