"""The length an address may be, and why anything longer is the domain's refusal.

``users.email`` is ``String(255)``. Nothing above it said so, so an address
of any length travelled the whole way down and was refused by PostgreSQL --
which does not raise ``ValidationError``, so no handler on the way out knew
it, and an **unauthenticated** two-field body to ``POST
/api/v1/auth/register`` answered ``500``. Measured on the production
profile with a 261-character address.

SQLite is why the suite never saw it: it ignores a declared width, stores
the row, and reports nothing. So a test that only asks "does registration
work" cannot find this class of fault at all -- which is why the bound is
held here, on the object that owns the rule, rather than only on the route.
"""

import pytest

from link_shortener.domain.exceptions import ValidationError
from link_shortener.domain.value_objects.email import (
    Email, MAX_EMAIL_LENGTH,
)


def an_address_of(length: int) -> str:
    """
    Build a syntactically valid address of exactly this many characters.

    Args:
        length: The total length wanted. Must leave room for
            ``@example.com``.

    Returns:
        An address the pattern accepts, of the length asked for.
    """
    suffix = "@example.com"
    local = "a" * (length - len(suffix))
    return local + suffix


class TestTheBoundIsTheStandardsOne:
    """Where the number comes from."""

    def test_it_is_254(self):
        """RFC 5321 caps a forward-path at 256 octets, brackets included.

        Stated as a test rather than only in a docstring because the
        column beside it is 255: someone widening the column later should
        find out here that the limit is not the column's.
        """
        assert MAX_EMAIL_LENGTH == 254

    def test_it_fits_the_column_it_protects(self):
        """The rule must never admit what the schema cannot hold."""
        assert MAX_EMAIL_LENGTH <= 255


class TestTheLongestAcceptedAddressIsAccepted:
    """The boundary, from below."""

    def test_exactly_the_limit_is_an_address(self):
        """Off-by-one in the safe direction is still off by one."""
        value = an_address_of(MAX_EMAIL_LENGTH)

        assert len(Email(value).value) == MAX_EMAIL_LENGTH

    def test_one_under_the_limit_is_an_address(self):
        """The ordinary case, kept beside the boundary it is next to."""
        value = an_address_of(MAX_EMAIL_LENGTH - 1)

        assert Email(value).value == value


class TestAnythingLongerIsRefusedHere:
    """The boundary, from above -- and by whom."""

    def test_one_over_the_limit_is_refused(self):
        """The first length that must not reach the database."""
        with pytest.raises(ValidationError):
            Email(an_address_of(MAX_EMAIL_LENGTH + 1))

    def test_the_refusal_names_the_field(self):
        """So the API answers 400 with ``field: email`` and not a 500."""
        with pytest.raises(ValidationError) as refused:
            Email(an_address_of(MAX_EMAIL_LENGTH + 1))

        assert refused.value.field == "email"

    def test_the_measured_length_is_refused(self):
        """261 characters: the body that actually produced the 500."""
        with pytest.raises(ValidationError):
            Email("a" * 250 + "@eval.local")

    def test_the_offending_value_is_not_in_the_message(self):
        """The same rule the shape check follows one line below it.

        This sentence reaches the client, and ``Email`` is also built from
        stored rows -- so echoing the value would reflect input on the way
        in and leak a stored address on the way out.
        """
        value = an_address_of(MAX_EMAIL_LENGTH + 40)

        with pytest.raises(ValidationError) as refused:
            Email(value)

        assert value not in str(refused.value)

    def test_length_is_judged_before_shape(self):
        """A long string that is also not an address meets this rule first.

        Not a preference about speed: the caller is better told which
        limit they met, and "too long" is the more useful half when both
        are true.
        """
        with pytest.raises(ValidationError) as refused:
            Email("x" * (MAX_EMAIL_LENGTH + 10))

        assert "long" in str(refused.value).lower()


class TestAStoredRowMeetsTheSameRule:
    """``from_storage`` validates, and this is part of what it validates."""

    def test_an_overlong_row_is_refused(self):
        """A row this long cannot be written once the rule exists.

        It can still be *found* -- SQLite ignores the width, so a database
        filled before the bound existed may hold one. That row is broken,
        and ``from_storage`` says so rather than carrying it further.
        """
        with pytest.raises(ValidationError):
            Email.from_storage(an_address_of(MAX_EMAIL_LENGTH + 1))
