from link_shortener.domain.value_objects.original_url import OriginalUrl
from link_shortener.domain.exceptions import ValidationError
import pytest


class TestOriginalUrl:
    """Tests for the OriginalUrl value object."""

    # ------------------------------------------------------------------
    # Valid URLs
    # ------------------------------------------------------------------
    @pytest.mark.parametrize("valid_url", [
        "https://test.com",
        "http://test.com",
        "https://sub.domain.test.com",
        "http://localhost",
        "http://127.0.0.1",
        "http://[::1]",
        "https://test.com:8080",
        "http://test.com/path",
        "https://test.com/path?query=1",
        "http://test.com#fragment",
        "https://test.com:443/path?q=1#frag",
    ])
    def test_valid_url_creates_object(self, valid_url):
        """Should create an OriginalUrl object from a valid URL string."""

        url = OriginalUrl(valid_url)
        assert url.value == valid_url


    # ------------------------------------------------------------------
    # Invalid URLs – general checks
    # ------------------------------------------------------------------
    @pytest.mark.parametrize("invalid_url,expected_error", [
        ("https://" + "a" * 2048, "URL too long"),
        ("", "URL must have a scheme"),
        ("ftp://test.com", "Scheme 'ftp' is not allowed"),
        ("https://test", "Host must contain a dot"),
        ("http://", "URL must have a domain!"),
        ("https://", "URL must have a domain!"),
    ])
    def test_invalid_url_raises_error(self, invalid_url, expected_error):
        """Should raise ValidationError for malformed URLs."""

        with pytest.raises(ValidationError, match=expected_error):
            OriginalUrl(invalid_url)
    

    # ------------------------------------------------------------------
    # Port validation
    # ------------------------------------------------------------------
    @pytest.mark.parametrize("invalid_port_url", [
        "http://test.com:0",
        "http://test.com:65536",
        "http://test.com:99999",
        "http://test.com:port",
    ])
    def test_invalid_port_raises_error(self, invalid_port_url):
        """Should raise ValidationError for invalid port numbers."""

        with pytest.raises(ValidationError, match="Invalid port number"):
            OriginalUrl(invalid_port_url)


    # ------------------------------------------------------------------
    # Host validation (domain name)
    # ------------------------------------------------------------------
    @pytest.mark.parametrize("invalid_host", [
        "http://.com",                  # empty label at start
        "http://test..com",          # empty label
        "http://te_st.com",          # invalid character _
        "http://-test.com",          # label starts with hyphen
        "http://test-.com",          # label ends with hyphen
        "http://a" + "b"*63 + ".com",   # label >63 chars
        "http://" + "a"*254 + ".com",   # total length >253
    ])
    def test_invalid_host_raises_error(self, invalid_host):
        """Should raise ValidationError for invalid hostnames."""

        with pytest.raises(ValidationError, match="Empty label in host|Invalid characters|Label too long|Host too long"):
            OriginalUrl(invalid_host)


    # ------------------------------------------------------------------
    # IP addresses (should be valid)
    # ------------------------------------------------------------------
    @pytest.mark.parametrize("valid_ip_url", [
        "http://192.168.1.1",
        "http://10.0.0.1",
        "http://[2001:db8::1]",
        "http://[::1]",
        "http://[::ffff:192.0.2.128]",
    ])
    def test_valid_ip_address(self, valid_ip_url):
        """Should accept valid IPv4 and IPv6 addresses."""

        url = OriginalUrl(valid_ip_url)
        assert url.value == valid_ip_url
    

    # ------------------------------------------------------------------
    # Path containing control characters
    # ------------------------------------------------------------------
    @pytest.mark.parametrize("path_with_control", [
        "http://test.com/\x00",
        "http://test.com/\x1F",
        "http://test.com/\x7F",
    ])
    def test_path_with_control_characters_raises_error(self, path_with_control):
        """Should raise ValidationError if path contains control characters."""

        with pytest.raises(ValidationError, match="Path contains control characters"):
            OriginalUrl(path_with_control)


    # ------------------------------------------------------------------
    # Tests for get_domain and normalize methods
    # ------------------------------------------------------------------
    def test_get_domain(self):
        """Should extract domain (hostname) without port."""

        url = OriginalUrl("https://sub.test.com:8080/path")
        assert url.get_domain() == "sub.test.com"

    @pytest.mark.parametrize("url,expected", [
        ("httPs://TesT.com", "https://test.com/"),
        ("https://test.com", "https://test.com/"),
        ("https://test.com/", "https://test.com/"),
        ("https://test.com/path?q=1#frag", "https://test.com/path?q=1"),
        ("http://TEST.com:8080/Path", "http://test.com:8080/Path"),
    ])
    def test_normalize(self, url, expected):
        """
        Should normalize URL to lowercase scheme/host, 
        add trailing slash if needed, and strip fragment.
        """

        assert OriginalUrl(url).normalize() == expected
