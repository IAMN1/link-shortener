from dataclasses import dataclass
import ipaddress
from typing import Tuple
from urllib.parse import ParseResult, urlparse
import re

from link_shortener.domain.exceptions import ValidationError

@dataclass(frozen=True)
class OriginalUrl:
    """
    Value object representing a validated original URL.

    Encapsulates URL validation rules and normalization logic.
    The object is immutable (frozen) after creation.

    Attributes:
        value: The original URL string.
        allowed_schemes: Tuple of permitted URL schemes (default http, https).

    Raises:
        ValidationError: If the URL does not pass validation (length, scheme, host, path).
    """

    value: str
    allowed_schemes: Tuple[str, ...] = ("http", "https")

    def __post_init__(self):
        """Validate the URL upon creation. Called automatically by dataclass."""

        self._validate_length()
        parsed = urlparse(self.value)
        self._validate_scheme(parsed)
        self._validate_netloc(parsed)
        self._validate_path(parsed)

    # ------------------------------------------------------------------
    # Validation methods
    # ------------------------------------------------------------------
    def _validate_length(self) -> None:
        """Ensure URL does not exceed the maximum allowed length."""

        if len(self.value) > 2048:
            raise ValidationError("URL too long (max 2048 characters)", field="url")

    def _validate_scheme(self, parsed: ParseResult) -> None:
        """Check that the scheme is present and allowed."""
        if not parsed.scheme:
            raise ValidationError("URL must have a scheme!", field="url")

        if parsed.scheme not in self.allowed_schemes:
            allowed_list = ", ".join(self.allowed_schemes)
            raise ValidationError(
                f"Scheme '{parsed.scheme}' is not allowed. "
                f"Allowed schemes: {allowed_list}",
                field="url",
            )

    def _validate_netloc(self, parsed: ParseResult) -> None:
        """Validate the network location (hostname and optional port)."""

        if not parsed.netloc:
            raise ValidationError("URL must have a domain!", field="url")

        hostname = parsed.hostname
        if not hostname:
            raise ValidationError("URL must have a hostname", field="url")

        # Validate port if present (must be between 1 and 65535)
        try:
            port = parsed.port
        except ValueError:
            raise ValidationError("Invalid port number", field="url")
        if port is not None and not (1 <= port <= 65535):
            raise ValidationError("Invalid port number", field="url")
        
        self._validate_host(hostname)
    
    def _validate_host(self, host: str) -> None:
        """
        Validate hostname: can be an IP address, 'localhost', or a valid domain.

        For domain names, each label must contain only alphanumeric chars and hyphens,
        cannot start or end with hyphen, and total length ≤ 253.
        """

        # Validate as a domain name.
        if not host:
            raise ValidationError("Empty host", field="url")

        # Check if it's a valid IP address (IPv4 or IPv6)
        try:
            ipaddress.ip_address(host)
            return # Valid IP, no further checks needed
        except ValueError:
            pass
        
        # Allow 'localhost' as a special name
        if host == "localhost":
            return

        # Otherwise must be a domain with at least one dot
        if '.' not in host:
            raise ValidationError("Host must contain a dot (e.g., example.com)", field="url")

        # Total length limit
        if len(host) > 253:
            raise ValidationError("Host too long", field="url")

        # Validate each label
        labels = host.split(".")
        for label in labels:
            if not label:
                raise ValidationError("Empty label in host", field="url")
            if len(label) > 63:
                raise ValidationError("Label too long", field="url")

            # Label must start/end with alphanumeric, may contain hyphens inside
            if not re.match(r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?$', label):
                raise ValidationError(f"Invalid characters in host label: {label}", field="url")
    
    def _validate_path(self, parsed) -> None:
        """Validate that the URL path does not contain control characters.

        Control characters (ASCII 0-31 and 127) are not allowed in the path.

        Args:
            parsed: The parsed URL result from urllib.parse.urlparse.

        Raises:
            ValidationError: If a control character is found in the path."""

        if parsed.path and any(ord(c) < 32 or ord(c) == 127 for c in parsed.path):
            raise ValidationError("Path contains control characters", field="url")

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------
    def __str__(self) -> str:
        """Return the original URL string."""
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
        - Remove default ports (80 for http, 443 for https).
        """
        parsed = urlparse(self.value)
        scheme=parsed.scheme.lower()
        netloc=parsed.netloc.lower()

        # Remove default ports
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
