"""Tests for logging helpers.

``mask_url`` is what stands between a stored URL and the audit log, so what
it does and does not do is worth stating explicitly.
"""

from link_shortener.infrastructure.logging.utils import mask_url


class TestMaskUrl:
    """Shortening of over-long URLs before they reach a log line."""

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

    def test_credentials_in_a_short_url_are_not_removed(self):
        """States what this function does NOT do.

        The name says "mask" and the audit loggers describe the result as
        masked "for privacy", but the only thing that happens is
        shortening. A URL carrying userinfo or a token in its query reaches
        the audit log intact whenever it is under the length limit -- and
        secrets are usually short.

        Asserted rather than left implicit so that the gap is visible here
        instead of being discovered in a log file.
        """
        url = "https://user:s3cret@example.com/?token=abc123"

        assert len(url) < 100
        assert mask_url(url) == url
        assert "s3cret" in mask_url(url)
        assert "token=abc123" in mask_url(url)
