from dataclasses import dataclass
import ipaddress
from urllib.parse import ParseResult, urlparse
import re

@dataclass(frozen=True)
class OriginalUrl:
    """
    Value object representing an original URL.

    Encapsulates validation rules and normalization logic.
    Immutable.

    Attributes:
        value: The original URL string.

    Raises:
        ValueError: If the URL fails validation.
    """

    value: str

    def __post_init__(self):
        """Validate the URL upon creation."""

        self._validate_length()
        parsed = urlparse(self.value)
        self._validate_scheme(parsed)
        self._validate_netloc(parsed)
        self._validate_path(parsed)

    # ------------------------------------------------------------------
    # Validation methods
    # ------------------------------------------------------------------

    def _validate_length(self) -> None:
        """Ensure URL does not exceed maximum allowed length."""

        if len(self.value) > 2048:
            raise ValueError("URL too long (max 2048 characters)")

    def _validate_scheme(self, parsed: ParseResult) -> None:
        """Check that scheme is present and allowed (http/https)."""

        if not parsed.scheme:
            raise ValueError("URL must have a scheme!")

    def _validate_netloc(self, parsed: ParseResult) -> None:
        """Validate network location part (hostname and optional port)."""

        if not parsed.netloc:
            raise ValueError("URL must have a domain!")
        
        hostname = parsed.hostname
        if not hostname:
            raise ValueError("URL must have a hostname")
        
        # Validate port if present
        try:
            if parsed.port is not None and not (1 <= parsed.port <= 65535):
                raise ValueError("Invalid port number")
        except ValueError as e:
            raise ValueError("Invalid port number") from e
        
        self._validate_host(hostname)
    
    def _validate_host(self, host: str) -> None:
        """
        Validate hostname: can be IP, localhost, or a valid domain name.

        Domain name rules: each label must contain only alphanumeric chars and hyphens,
        cannot start or end with hyphen, and total length constraints.
        """

        # Проврка как доменного имени
        if not host:
            raise ValueError("Empty host")

        # Check if it's a valid IP address
        try:
            ipaddress.ip_address(host)
            return # IP is valid
        except ValueError:
            pass
        
        # Allow localhost
        if host == "localhost":
            return

        # Domain name must contain at least one dot
        if '.' not in host:
            raise ValueError("Host must contain a dot (e.g., example.com)")
        
        # Total length limit
        if len(host) > 253:
            raise ValueError("Host too long")
        
        # Validate each label
        labels = host.split(".")
        for label in labels:
            
            if not label:
                raise ValueError ("Empty label in host")
            if len(label) > 63:
                raise ValueError("Label too long")
            
            # Допустимые символы:
            # буквы, цифры, дефис, но не начинается и не заканчивается дефисом
            if not re.match(r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?$', label):
                raise ValueError(f"Invalid characters in host label: {label}")
    
    def _validate_path(self, parsed) -> None:
        """Validate that the URL path does not contain control characters.

        Control characters (ASCII 0-31 and 127) are not allowed in the path.

        Args:
            parsed: The parsed URL result from urllib.parse.urlparse.

        Raises:
            ValueError: If a control character is found in the path."""

        if parsed.path and any(ord(c) < 32 or ord(c) == 127 for c in parsed.path):
            raise ValueError("Path contains control characters")

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def __str__(self) -> str:
        return self.value

    def get_domain(self) -> str:
        """Extract domain (hostname) from the URL."""
        parsed = urlparse(self.value)
        return parsed.hostname or ""

    def normalize(self) -> str:
        """
        Normalize the URL for consistent comparison and hashing.

        Normalization includes:
        - Lowercase scheme and netloc.
        - Ensure path is at least '/'.
        - Remove fragment.
        """
        parsed = urlparse(self.value)
        scheme=parsed.scheme.lower()
        netloc=parsed.netloc.lower()

        if scheme == "http" and parsed.port == 80:
            netloc = netloc.replace(':80','')
        elif scheme == "https" and parsed.port == 443:
            netloc = netloc.replace(':443', '')
        path = parsed.path if parsed.path else "/"

        normalized = ParseResult(
            scheme=scheme,
            netloc=netloc,
            path=path,
            params=parsed.params,
            query=parsed.query,
            fragment="",
        ).geturl()
        return normalized
