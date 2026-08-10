"""An address names one account, whatever case it is typed in.

``find_by_email`` compares the stored string, and the unique index on
``users.email`` compares it too, so whether ``Case@Example.com`` and
``case@example.com`` are one account or two is decided here and nowhere
else. It used to be two: a second account for the same mailbox, two
confirmation links, and a sign-in that worked or failed depending on how
the address had been capitalised the first time.

The rule is asymmetric in the standard and deliberately not here. RFC 5321
section 2.4 says mailbox domains "follow normal DNS rules and are hence
not case sensitive", while "The local-part of a mailbox MUST BE treated as
case sensitive" -- and then, in the same paragraph, that exploiting that
sensitivity "impedes interoperability and is discouraged". Django resolves
it by lowering the domain alone; this lowers both, and the developer guide
records what that buys and what it costs.
"""

import pytest

from link_shortener.domain import Email, ValidationError


class TestOneAddressIsOneAccount:
    """Two spellings of one mailbox must compare equal."""

    def test_the_local_part_is_lowered(self):
        assert Email("Case@example.com").value == "case@example.com"

    def test_the_domain_is_lowered(self):
        assert Email("case@Example.COM").value == "case@example.com"

    def test_a_shouted_address_is_the_quiet_one(self):
        assert Email("CASE@EXAMPLE.COM").value == "case@example.com"

    def test_two_spellings_are_the_same_value(self):
        """The dataclass compares by field, so this is what the repository
        and the unique index end up comparing."""
        assert Email("Case@Example.com") == Email("case@example.com")

    def test_an_already_lower_address_is_untouched(self):
        assert Email("case@example.com").value == "case@example.com"

    def test_it_lowers_and_does_not_fold(self):
        """``casefold()`` is the tempting upgrade and the wrong one here.

        It exists for caseless *matching* of text and rewrites letters:
        ``'Straße'.casefold()`` is ``'strasse'``, so ``strasse@x`` and
        ``straße@x`` -- two different mailboxes -- would become one
        account, and mail would go to an address nobody typed. Lowering
        maps each letter to its own lower case and leaves ``ß`` alone.
        """
        assert Email("Straße@Example.COM").value == "straße@example.com"


class TestWhatNormalisingMustNotQuietlyAllow:
    """Case is the only thing that changes. The rest of the rule stands."""

    @pytest.mark.parametrize(
        "address",
        [
            "case@example.com\n",
            "case@example.com\r",
            " case@example.com",
            "case@example.com ",
            "ca se@example.com",
        ],
    )
    def test_whitespace_is_still_refused(self, address):
        """Trimming would have been the obvious companion to lowering, and
        it would quietly accept the trailing newline this pattern refuses
        on purpose: the address goes into a mail header, and a newline in
        a header is how an injection is spelled."""
        with pytest.raises(ValidationError):
            Email(address)

    @pytest.mark.parametrize(
        "address", ["not-an-address", "two@at@example.com", "no-dot@example"]
    )
    def test_a_malformed_address_is_still_refused(self, address):
        with pytest.raises(ValidationError):
            Email(address)

    def test_the_refusal_does_not_echo_the_address(self):
        """The message reaches the client, and this object is also built
        from database rows on the read path."""
        with pytest.raises(ValidationError) as raised:
            Email("SECRET-VALUE@@example.com")

        assert "SECRET-VALUE" not in str(raised.value)
