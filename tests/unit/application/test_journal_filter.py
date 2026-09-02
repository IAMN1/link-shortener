"""What a search over a journal matches, and what it deliberately does not.

The filter is where a question asked on a page becomes a decision about
each line, so the shape of the answers matters more than it looks. Two
choices are worth holding here: an identifier matches exactly, because a
substring of one is a different identifier rather than a weaker question;
and a time bound matches by prefix, because the stamps are ISO 8601 in UTC
and sort as text, so a date names a day at either end of a range without
any parsing or clock arithmetic.
"""

import pytest

from link_shortener.application.ports.journal_reader import (
    HEALTH_PROBE_EVENT_TYPE, JournalFilter,
)


def record(**overrides) -> dict:
    """
    A record in the shape the audit journal carries.

    Args:
        **overrides: Fields to change or add.

    Returns:
        The fields of one line.
    """
    fields = {
        "event_type": "URL_ACCESSED",
        "short_code": "-gxXupR",
        "user_id": "who-asked",
        "remote_addr": "172.18.0.1",
        "timestamp": "2026-08-18T10:46:53Z",
    }
    fields.update(overrides)
    return fields


class TestAnEmptyFilterIsNotAFilter:
    """It matches everything, so a reader can always pass one."""

    def test_it_says_so(self):
        assert JournalFilter().is_empty is True

    def test_any_field_makes_it_a_filter(self):
        assert JournalFilter(account="u-1").is_empty is False
        assert JournalFilter(since="2026-08-18").is_empty is False

    def test_it_matches_a_record(self):
        assert JournalFilter().matches(record()) is True

    def test_it_matches_a_line_that_did_not_parse(self):
        """Nothing was asked, so nothing can exclude it -- and a viewer
        showing unparsed lines is the reason they are kept at all."""
        assert JournalFilter().matches({}) is True


class TestTheIdentifiersMatchExactly:
    """A substring of an identifier is a different identifier."""

    def test_an_event_type(self):
        where = JournalFilter(event_type="LOGIN_FAILED")

        assert where.matches(record(event_type="LOGIN_FAILED")) is True
        assert where.matches(record(event_type="LOGIN_SUCCEEDED")) is False

    def test_an_address_is_not_matched_by_containment(self):
        """``110.0.0.199`` contains ``10.0.0.1`` and is another machine."""
        where = JournalFilter(remote_addr="10.0.0.1")

        assert where.matches(record(remote_addr="10.0.0.1")) is True
        assert where.matches(record(remote_addr="110.0.0.199")) is False

    def test_a_short_code(self):
        where = JournalFilter(short_code="-gxXupR")

        assert where.matches(record(short_code="-gxXupR")) is True
        assert where.matches(record(short_code="-gxXup")) is False

    def test_a_field_the_record_does_not_carry_never_matches(self):
        """Half the events have no short code at all: a login is not a
        weaker answer to "what happened to this link"."""
        where = JournalFilter(short_code="-gxXupR")
        login = {"event_type": "LOGIN_FAILED", "timestamp": "2026-08-18T10:00:00Z"}

        assert where.matches(login) is False


class TestOneAccountFieldReachesBothNames:
    """The events split by whether the account acted or was acted upon."""

    def test_the_account_that_acted(self):
        assert JournalFilter(account="u-1").matches(record(user_id="u-1")) is True

    def test_the_account_that_was_acted_upon(self):
        line = {"event_type": "ROLES_CHANGED", "target_user_id": "u-1",
                "user_id": "the-administrator"}

        assert JournalFilter(account="u-1").matches(line) is True

    def test_an_administrator_is_still_found_by_their_own_id(self):
        """Both names are read, so the same search answers for either side
        of the same record."""
        line = {"event_type": "ROLES_CHANGED", "target_user_id": "u-1",
                "user_id": "the-administrator"}

        assert JournalFilter(account="the-administrator").matches(line) is True

    def test_an_account_that_appears_nowhere_in_the_record(self):
        assert JournalFilter(account="somebody-else").matches(record()) is False


class TestTheTimeBoundsAreInclusiveAtBothEnds:
    """A day named as the end of a range is part of the range."""

    @pytest.mark.parametrize(
        "stamp, expected",
        [
            ("2026-08-17T23:59:59Z", False),
            ("2026-08-18T00:00:00Z", True),
            ("2026-08-18T10:46:53Z", True),
            ("2026-08-18T23:59:59Z", True),
            ("2026-08-19T00:00:00Z", False),
        ],
    )
    def test_a_single_day_named_at_both_ends(self, stamp, expected):
        """The case the prefix comparison exists for.

        Compared whole rather than by prefix, every moment of the 18th
        would sort after the bound ``2026-08-18`` and the day named as the
        end of the range would hold nothing at all.
        """
        where = JournalFilter(since="2026-08-18", until="2026-08-18")

        assert where.matches(record(timestamp=stamp)) is expected

    def test_an_hour_is_a_prefix_like_any_other(self):
        where = JournalFilter(since="2026-08-18T10", until="2026-08-18T10")

        assert where.matches(record(timestamp="2026-08-18T10:46:53Z")) is True
        assert where.matches(record(timestamp="2026-08-18T11:00:00Z")) is False

    def test_only_one_end_may_be_given(self):
        assert JournalFilter(since="2026-08-18").matches(
            record(timestamp="2027-01-01T00:00:00Z")
        ) is True
        assert JournalFilter(until="2026-08-18").matches(
            record(timestamp="2020-01-01T00:00:00Z")
        ) is True

    def test_a_record_with_no_stamp_falls_outside_every_range(self):
        """It cannot be placed in time, and a bounded search is asking
        exactly where it falls."""
        where = JournalFilter(since="2026-08-18")

        assert where.matches({"event_type": "LOGIN_FAILED"}) is False

    def test_a_stamp_that_is_not_a_string_is_not_compared(self):
        """A number where the stamp belongs would otherwise reach a
        comparison between ``int`` and ``str``, which raises."""
        where = JournalFilter(since="2026-08-18")

        assert where.matches(record(timestamp=1787053487)) is False


class TestEveryTermGivenMustMatch:
    """Terms narrow the answer; they do not widen it."""

    def test_all_of_them_together(self):
        where = JournalFilter(
            event_type="URL_ACCESSED",
            account="who-asked",
            remote_addr="172.18.0.1",
            short_code="-gxXupR",
            since="2026-08-18",
            until="2026-08-18",
        )

        assert where.matches(record()) is True

    def test_one_of_them_failing_is_enough(self):
        where = JournalFilter(event_type="URL_ACCESSED", account="somebody-else")

        assert where.matches(record()) is False

    def test_a_line_that_did_not_parse_matches_no_filter(self):
        """It has no fields to match on. Letting it through would answer a
        search for one account with every torn line in the file."""
        assert JournalFilter(account="u-1").matches({}) is False


class TestTheChainsOwnProbeIsNotWhatAReaderCameFor:
    """
    The health probe writes into the journal it is probing.

    It has to: a probe that does not write cannot find out whether the
    chain can still write. But at four workers and the seeded thirty-second
    interval that is eight lines a minute in each of `application.log` and
    `audit.log` -- measured on the running stack over eight consecutive
    minutes -- and it filled 25 of the 50 lines on the first screen of the
    journals page. A reader who came to see what happened was shown the
    service checking itself.

    So the plain tail drops them and the search brings them back. The lines
    stay in the file either way, which is the point: a gap in them is how a
    reader afterwards can tell the chain stopped writing.
    """

    PROBE = {
        "event_type": HEALTH_PROBE_EVENT_TYPE,
        "event": "logging chain health probe",
        "timestamp": "2026-08-18T10:46:53Z",
    }

    def test_the_plain_tail_does_not_show_it(self):
        assert JournalFilter().matches(self.PROBE) is False

    def test_asking_for_it_by_name_shows_it(self):
        asked = JournalFilter(event_type=HEALTH_PROBE_EVENT_TYPE)

        assert asked.matches(self.PROBE) is True

    def test_another_search_does_not_drag_it_in(self):
        """A term the probe does not carry must not answer with it."""
        for asked in (
            JournalFilter(event_type="URL_ACCESSED"),
            JournalFilter(account="who-asked"),
            JournalFilter(since="2026-08-18"),
        ):
            assert asked.matches(self.PROBE) is False, asked

    def test_the_records_a_reader_came_for_are_untouched(self):
        """The premise: this hides one event type and no others.

        Without it the assertions above are satisfied by a filter that
        matches nothing at all.
        """
        assert JournalFilter().matches(record()) is True
        assert JournalFilter(short_code="-gxXupR").matches(record()) is True
        assert JournalFilter(
            event_type=HEALTH_PROBE_EVENT_TYPE
        ).matches(record()) is False

    def test_a_line_that_did_not_parse_is_still_shown(self):
        """An empty record carries no event type, so nothing hides it."""
        assert JournalFilter().matches({}) is True

    def test_the_rest_of_the_search_still_applies_to_it(self):
        """
        Asking for the probe by name lifts the hiding and nothing else.

        The branch answered ``True`` outright, so every other term of the
        same search was skipped: an operator narrowing to one day -- which
        is the whole way to find the gap where the chain stopped writing --
        was handed the probes of every day in the live file and in the
        archives, and the gap was pushed off the page by them.
        """
        by_name = HEALTH_PROBE_EVENT_TYPE

        assert JournalFilter(
            event_type=by_name, since="2026-08-18", until="2026-08-18"
        ).matches(self.PROBE) is True

        assert JournalFilter(
            event_type=by_name, since="2026-09-01", until="2026-09-01"
        ).matches(self.PROBE) is False

        assert JournalFilter(
            event_type=by_name, remote_addr="10.0.0.1"
        ).matches(self.PROBE) is False
