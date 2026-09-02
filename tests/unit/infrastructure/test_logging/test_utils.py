"""Tests for logging helpers.

``mask_url`` is what stands between a stored URL and the audit log, so what
it does and does not do is worth stating explicitly. ``mask_email`` stands
in the same place for the address of an account.
"""

from link_shortener.infrastructure.logging.utils import mask_email, mask_url


class TestMaskUrl:
    """What is removed from a URL, and what is merely shortened, before it
    reaches a log line."""

    def test_short_url_is_returned_unchanged(self):
        """Nothing is done to a URL that fits."""
        url = "https://example.com/some/path?a=1"

        assert mask_url(url) == url

    def test_url_at_the_boundary_is_left_alone(self):
        """The rule is "longer than 100", so exactly 100 passes."""
        url = "https://example.com/" + "a" * 80

        assert len(url) == 100
        assert mask_url(url) == url

    def test_long_url_is_shortened_to_its_two_ends(self):
        """A long URL keeps its first 50 and last 20 characters."""
        url = "https://example.com/" + "b" * 200

        masked = mask_url(url)

        assert masked == f"{url[:50]}...{url[-20:]}"
        assert len(masked) == 73
        assert len(masked) < len(url)

    def test_shortening_keeps_the_origin_readable(self):
        """The point of keeping the head is knowing where it pointed."""
        url = "https://example.com/" + "c" * 200

        assert mask_url(url).startswith("https://example.com/")

    def test_credentials_are_removed_from_a_short_url(self):
        """The case the length rule could never have caught.

        This URL is 45 characters, so truncation leaves it whole -- and
        secrets are short by nature. Without removal it reaches the audit
        log with the password in it.
        """
        url = "https://user:s3cret@example.com/?token=abc123"
        assert len(url) < 100

        masked = mask_url(url)

        assert masked == "https://***@example.com/?token=abc123"
        assert "s3cret" not in masked
        assert "user" not in masked

    def test_credentials_are_removed_before_the_url_is_cut(self):
        """Order matters, and long credentials are what prove it.

        With a short password either order works: the cut keeps the first
        50 characters, the ``@`` survives inside them, and removal still
        finds an authority to clean. Past about 42 characters of userinfo
        the cut lands before the ``@`` -- and then cutting first hands
        back the head of the password verbatim: on this input, 37 of its
        60 characters.
        """
        password = "S" * 60
        url = f"https://user:{password}@example.com/" + "d" * 200

        masked = mask_url(url)

        assert "SSSSSSSSSS" not in masked
        assert masked.startswith("https://***@example.com/")

    def test_a_lone_username_goes_too(self):
        """No password does not mean nothing worth removing."""
        assert mask_url("https://admin@example.com/x") == (
            "https://***@example.com/x"
        )

    def test_an_address_without_credentials_is_untouched(self):
        """Byte for byte: reassembly normalises, the audit records what
        was submitted."""
        url = "HTTPS://Example.COM:443/Path/../x?b=2&a=1#f"

        assert mask_url(url) == url

    def test_an_ipv6_host_keeps_its_brackets(self):
        """The authority is not simply "text before the first slash"."""
        assert mask_url("http://a:b@[::1]:8080/p?q=1") == (
            "http://***@[::1]:8080/p?q=1"
        )

    def test_something_that_is_not_a_url_is_left_as_it_is(self):
        """Neither of these raises; ``urlsplit`` parses both happily and
        finds no authority to clean."""
        assert mask_url("not a url at all") == "not a url at all"
        assert mask_url("") == ""

    def test_an_input_that_cannot_be_parsed_does_not_raise(self):
        """The branch the two above do not reach.

        ``urlsplit`` raises on a malformed IPv6 literal, and a log line is
        not worth an exception in the caller's path -- the record would
        take the request down with it. What the branch must NOT do is hand
        the secret back: it used to, because giving up on parsing was read
        as giving up on masking. The embedded-address pattern needs no
        parse, so it cleans this one anyway.
        """
        assert mask_url("https://user:pw@[::1") == "https://***@[::1"
        assert mask_url("http://[]") == "http://[]"

    def test_an_at_sign_outside_the_authority_is_not_credentials(self):
        """The ``@`` is looked for in the authority, not in the URL.

        A path or query may hold one legitimately, and treating that as a
        credential separator rewrites -- or, with a naive split, crashes
        on -- an ordinary address.
        """
        url = "https://example.com/mail@example.org?to=a@b.com"

        assert mask_url(url) == url

    def test_the_last_at_sign_is_the_separator(self):
        """A password may not contain a bare ``@`` -- but an input that
        breaks the rules must still not leak.

        Splitting on the first ``@`` would leave everything between it and
        the host in place, which on this input is the password.

        The scheme-relative form is the one that proves it. With a scheme
        the embedded-address pattern reaches the same answer by itself, so
        an ``https://`` example passes either way and pins nothing; ``//``
        is not matched by that pattern, which leaves the split in
        ``_without_userinfo`` as the only thing standing between the
        password and the log.
        """
        assert mask_url("https://user:pass@word@example.com/x") == (
            "https://***@example.com/x"
        )
        assert mask_url("//user:pass@word@example.com/x") == (
            "//***@example.com/x"
        )

    def test_the_authority_is_parsed_where_the_pattern_cannot_reach(self):
        """What ``_without_userinfo`` alone is holding.

        Two shapes have credentials in a real authority and no
        ``scheme://`` for the embedded-address pattern to match: the
        scheme-relative form, and one whose userinfo holds a space --
        ``urlsplit`` keeps it, the pattern's ``\\s`` stops on it. Without
        this test the parsing half of the masking could be deleted whole
        and the suite would not notice.
        """
        assert mask_url("//user:s3cret@example.com/x") == "//***@example.com/x"
        assert mask_url("https://us er:s3cret@example.com/x") == (
            "https://***@example.com/x"
        )

    def test_credentials_in_an_embedded_address_are_removed(self):
        """The shape the entry check lets through.

        ``_validate_no_credentials`` looks at the authority, and this
        URL's authority is ``example.com`` -- clean. The ``@`` is in the
        query, so the address is admitted, stored, and read back into the
        audit log. Nothing else in the pipeline looks at it.
        """
        url = "https://example.com/r?next=https://alice:s3cret@evil.example/"

        masked = mask_url(url)

        assert masked == "https://example.com/r?next=https://***@evil.example/"
        assert "s3cret" not in masked

    def test_every_embedded_address_is_cleaned_not_just_the_first(self):
        """Two parameters, two secrets.

        A substitution that stops after one match leaves the second whole,
        and one leaked password is as bad as two.
        """
        url = "https://a.example/?a=https://x:pw1@h1/&b=ftp://z:pw2@h2/"

        masked = mask_url(url)

        assert masked == "https://a.example/?a=https://***@h1/&b=ftp://***@h2/"
        assert "pw1" not in masked
        assert "pw2" not in masked

    def test_the_last_at_sign_wins_inside_an_embedded_address_too(self):
        """A password containing ``@`` breaks the rules and must not leak.

        Taking the *first* ``@`` of the embedded authority leaves the tail
        of the password in place. The outer ``_without_userinfo`` cannot
        cover for this one: the outer authority is clean, so it hands the
        string straight on.
        """
        masked = mask_url("https://a.example/?u=https://x:p@sss3cret@evil.example/")

        assert masked == "https://a.example/?u=https://***@evil.example/"
        assert "s3cret" not in masked

    def test_any_scheme_is_matched_not_a_list_of_known_ones(self):
        """A stored URL may embed an address of any scheme.

        Narrowing the pattern to ``https?|ftp`` passes every test that
        uses those and lets everything else through -- and a connection
        string is exactly the sort of thing that carries a password.
        """
        masked = mask_url(
            "https://a.example/?u=redis://user:s3cret@cache.example:6379/0"
        )

        assert masked == "https://a.example/?u=redis://***@cache.example:6379/0"

    def test_a_long_embedded_authority_is_still_cleaned(self):
        """No length bound on the userinfo.

        A bounded repeat looks harmless and passes on every short input in
        this file, while leaving exactly the long secrets that matter.
        """
        password = "S" * 200
        masked = mask_url(f"https://a.example/?u=https://user:{password}@evil.example/")

        assert masked == "https://a.example/?u=https://***@evil.example/"

    def test_the_pattern_does_not_reach_across_a_space(self):
        """Two things in one string are not one authority.

        Without the whitespace bound this input is rewritten to name
        ``corp.example`` as the destination -- an address nobody
        submitted -- and the rest of the text disappears with it.
        """
        url = "https://a.example/?note=https://docs.example and ask bob@corp.example"

        assert mask_url(url) == url

    def test_an_embedded_address_in_the_fragment_is_cleaned_too(self):
        """The fragment is no safer than the query: both are logged."""
        masked = mask_url("https://example.com/#u=ftp://bob:pw@files.example/")

        assert masked == "https://example.com/#u=ftp://***@files.example/"

    def test_an_at_sign_after_the_authority_closes_is_left_alone(self):
        """The bound is RFC 3986's, not "an ``@`` anywhere".

        Both of these carry an embedded ``https://`` *and* an ``@``, and a
        pattern that merely looked for the two would rewrite an address
        that hides nothing -- making the audit trail lie about what was
        submitted. The ``@`` here follows a ``/``, so the authority it
        would have belonged to is already closed.
        """
        for url in (
            "https://example.com/?u=https://cdn.example/a@2x.png",
            "https://example.com/img@2x.png",
        ):
            assert mask_url(url) == url

    def test_credentials_with_no_scheme_at_all_still_get_through(self):
        """States the second thing this function does NOT do.

        ``user:pass@example.com/x`` has no authority for ``urlsplit`` to
        find and no ``://`` for the embedded-address pattern, so it passes
        whole. Reaching it would need a heuristic over arbitrary text, and
        neither shape can enter storage in the first place: ``urlparse``
        reads what precedes the first ``:`` as the scheme, so these arrive
        at ``_validate_scheme`` as ``user`` and ``mailto`` and are refused
        there -- before ``_validate_authority_present`` is ever consulted.
        Written down so the gap is visible here rather than in a log file.
        """
        assert mask_url("user:s3cret@example.com/x") == (
            "user:s3cret@example.com/x"
        )
        assert mask_url("mailto:user:s3cret@example.com") == (
            "mailto:user:s3cret@example.com"
        )

    def test_an_embedded_secret_is_removed_before_the_url_is_cut(self):
        """Order matters for the embedded case as well.

        The secret sits past character 50 and before the last 20, so
        truncation alone hides it -- and would keep hiding it right up
        until a shorter outer URL puts it back in view. Cutting first
        leaves the head of the password intact.
        """
        password = "S" * 60
        url = (
            "https://example.com/redirect?to=https://user:"
            f"{password}@evil.example/" + "d" * 40
        )

        masked = mask_url(url)

        assert len(url) > 100
        assert "SSSSSSSSSS" not in masked
        assert "https://***@evil.example/" in masked

    def test_a_percent_encoded_embedded_address_gets_through(self):
        """States the third thing this function does NOT do.

        ``urlencode`` produces exactly this spelling, so it is the
        ordinary shape of a redirect parameter rather than an exotic one --
        and the value passes the entry check, so it reaches the audit log
        by the front door. Reaching it would mean decoding the query
        before searching, and the audit trail is supposed to record what
        was submitted; partial encoding also gives many spellings of one
        string. Written down here rather than left to be discovered.
        """
        url = (
            "https://example.com/r?next="
            "https%3A%2F%2Fal%3As3cret%40evil.example%2F"
        )

        assert mask_url(url) == url

    def test_a_token_in_the_query_still_gets_through(self):
        """States what this function still does NOT do.

        Removing query secrets needs a list of parameter names, and such a
        list is never complete. Written down here so the gap is visible in
        the tests rather than discovered in a log file.
        """
        masked = mask_url("https://example.com/?token=abc123")

        assert "token=abc123" in masked


class TestMaskEmail:
    """What survives of an address written into the audit journal.

    Enough to ask the questions the journal is read with -- is one account
    being guessed at, or many; is the domain one that belongs here -- and
    not enough to be a list of this service's users. The whole address is
    still in ``application.log``, which is read under a different
    permission.
    """

    def test_the_local_part_is_reduced_to_one_character(self):
        assert mask_email("ivanov@example.com") == "i***@example.com"

    def test_the_domain_survives_whole(self):
        """The domain is the half an operator reasons about."""
        assert mask_email("a.very.long.name@mail.example.org").endswith(
            "@mail.example.org"
        )

    def test_two_addresses_on_one_domain_stay_distinguishable(self):
        """One character is little, but it is not nothing."""
        assert mask_email("alice@example.com") != mask_email("bob@example.com")

    def test_the_same_address_masks_the_same_way(self):
        """Repeated failures against one account have to look repeated."""
        assert mask_email("ivanov@example.com") == mask_email("ivanov@example.com")

    def test_a_string_that_is_not_an_address_is_masked_whole(self):
        """Nothing is known about it except where it was put."""
        assert mask_email("not-an-address") == "***"

    def test_an_empty_local_part_leaves_nothing_to_show(self):
        assert mask_email("@example.com") == "***@example.com"

    def test_the_domain_is_taken_after_the_last_at(self):
        """A quoted local part may hold an ``@``; a domain may not."""
        assert mask_email('"odd@name"@example.com') == '"***@example.com'

    def test_the_address_never_survives_in_full(self):
        address = "ivanov@example.com"

        assert address not in mask_email(address)
