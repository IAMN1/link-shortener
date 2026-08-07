from dataclasses import dataclass, field
import ipaddress
import re
from typing import Optional, Tuple, Union
from urllib.parse import ParseResult, urlparse

import idna

from link_shortener.domain.exceptions import ValidationError


IpAddress = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]

DEFAULT_PORTS = {"http": 80, "https": 443}
"""Ports a scheme is allowed to omit.

RFC 3986 §6.2.3 calls ``http://example.com:80/`` and ``http://example.com/``
the same resource, so normalization drops the port and the two deduplicate
into one link.
"""

SPECIAL_USE_SUFFIXES = (
    # Reserved by the IETF and by ICANN.
    "localhost",     # RFC 6761
    "local",         # RFC 6762, mDNS -- and Kubernetes' cluster.local
    "home.arpa",     # RFC 8375
    "internal",      # ICANN, 2024 -- where metadata.google.internal lives
    "alt",           # RFC 9476
    # Withheld by ICANN from delegation precisely because deployments
    # already use them inside their own networks (SAC 113).
    "corp",
    "home",
    "mail",
    # Not reserved anywhere, and resolvable only inside the network that
    # defines them -- through a search domain, a private zone or /etc/hosts.
    "localdomain",
    "intranet",
    "lan",
    "private",
    "svc",             # Kubernetes services, via the cluster search domain
    "consul",
    "novalocal",       # OpenStack instances
    "openstacklocal",
)
"""Name suffixes for names that exist only inside somebody's own network.

A name under any of these cannot belong to a public destination: none of
them is a delegated top-level domain, so nothing outside the network that
defines them can answer for one. Admitting them meant a short link could
aim at ``kubernetes.default.svc`` -- the cluster's API server -- from the
victim's browser, inside the victim's cluster.
"""

LABEL_PATTERN = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?$")
"""A single host label: alphanumeric ends, hyphens allowed inside."""

_RADIX_DIGITS = {
    8: re.compile(r"^[0-7]*$"),
    10: re.compile(r"^[0-9]+$"),
    16: re.compile(r"^[0-9a-fA-F]+$"),
}
"""Digits admissible for each radix of the IPv4 parser.

Matched by hand rather than left to ``int(s, radix)``, which also accepts
underscores as separators, a leading sign and surrounding whitespace --
none of which any resolver would.
"""


@dataclass(frozen=True)
class OriginalUrl:
    """
    Value object representing a validated original URL.

    Encapsulates URL validation rules and normalization logic.
    The object is immutable (frozen) after creation.

    Attributes:
        value: The original URL string.
        allowed_schemes: Tuple of permitted URL schemes (default http, https).
            Not part of the object's identity: a URL is its value, while the
            set of schemes the service happens to admit is a setting that
            can differ between the moment a URL is stored and the moment it
            is read back.
        max_length: Longest URL the service admits. Same reasoning as
            ``allowed_schemes``: a setting, not part of the identity.
        allow_internal_targets: When ``True``, addresses inside the
            deployment's own network are admitted as destinations. Off by
            default; see ``_validate_public_target``.

    Raises:
        ValidationError: If the URL does not pass validation (length, scheme, host, path).
    """

    value: str
    allowed_schemes: Tuple[str, ...] = field(
        default=("http", "https"), compare=False
    )
    max_length: int = field(default=2048, compare=False)
    allow_internal_targets: bool = field(default=False, compare=False)
    trusted: bool = field(default=False, compare=False, repr=False)
    """``True`` when the value comes from this service's own storage.

    Admission rules -- length, the scheme list, control characters,
    credentials, the ban on internal destinations -- are then skipped,
    because they decide what may *enter* and re-deciding them on the way out
    makes stored rows unreadable. Format rules still run.
    """

    def __post_init__(self):
        """Validate the URL upon creation. Called automatically by dataclass."""

        if not self.trusted:
            self._validate_length()
            self._validate_admissible_characters()
        parsed = self._parse()
        if not self.trusted:
            self._validate_scheme(parsed)
        self._validate_authority_present(parsed)
        if not self.trusted:
            self._validate_no_credentials(parsed)
            self._validate_bracketed_host_is_an_address(parsed)
            self._validate_netloc(parsed)
            self._validate_path(parsed)
            self._validate_public_target(parsed)

    def _parse(self) -> ParseResult:
        """
        Split the URL into components.

        ``urlparse`` raises plain ``ValueError`` for a handful of inputs --
        an unbalanced bracket, an empty one, a malformed IPvFuture literal,
        and twenty-one code points its NFKC check refuses in the authority,
        of which ``http://good.example℀evil.example/`` is one. A
        ``ValueError`` out of a value object is an error outside the domain's
        own hierarchy: whoever catches ``ValidationError`` does not catch it,
        and on the redirect path it reached the catch-all as a 500.

        Returns:
            The parsed URL.

        Raises:
            ValidationError: If the URL cannot be split at all.
        """
        try:
            return urlparse(self.value)
        except ValueError as exc:
            raise ValidationError(f"Malformed URL: {exc}", field="url")

    @classmethod
    def from_storage(cls, value: str) -> "OriginalUrl":
        """
        Rebuild a URL that the service already accepted and stored.

        Admission rules -- the length limit, the scheme list, the ban on
        control characters, on credentials and on internal destinations --
        decide what may *enter*. Each of them is either a setting an operator
        can widen and narrow, or a rule newer than some stored rows.
        Re-deciding any of them on the way out makes those rows unreadable,
        and one unreadable row is enough to fail an entire maintenance sweep
        or to answer 400 for a link that redirects perfectly well. This is
        the same defect class as the email value object rejecting values it
        had itself written -- and it is also what lets the sweep delete rows
        admitted under rules since tightened.

        The format rules are skipped too, and for the same reason rather
        than a weaker one. They are no less a decision about what may enter,
        and they have moved as well: the label pattern, the length ceiling,
        the ban on control characters in the path and the port range are all
        newer than rows written under earlier ones. A row they refuse is a
        row nothing in the product can reach -- and ``clean_expired_links``
        converts a whole chunk before deleting any of it, so one such row
        stops every sweep from that point on, including the sweep that would
        have removed it. ``GET /links/mine``, ``GET /stats`` and
        ``flask link list`` fail the same way, on the whole answer.
        Measured: one row with an underscore in a host label left five
        healthy expired links undeleted, and no command in the service could
        take any of them out.

        What still runs is parsing, because a string that cannot be split
        into components is not a URL in any sense and nothing downstream --
        ``normalize()``, ``get_domain()`` -- can work with it.

        Args:
            value: URL string as stored.

        Returns:
            The reconstructed value object.
        """
        return cls(value, trusted=True)

    # ------------------------------------------------------------------
    # Validation methods
    # ------------------------------------------------------------------
    def _validate_length(self) -> None:
        """Ensure URL does not exceed the maximum allowed length."""

        if len(self.value) > self.max_length:
            raise ValidationError(
                f"URL too long (max {self.max_length} characters)", field="url"
            )

    def _validate_admissible_characters(self) -> None:
        """
        Reject control characters anywhere in the submitted URL.

        Checked against the **raw string**, before parsing, and not against
        any parsed component. ``urlsplit`` deletes ASCII tab, CR and LF from
        the input at any position -- WHATWG behaviour that Python adopted --
        so a check on a parsed component can never see them, and the
        library's own documentation says as much: it does not validate, and
        callers are expected to verify the input themselves.

        What that let through:

        - ``https://host/page#\\n`` was accepted, stored raw, and then
          crashed the redirect for good, because an HTTP ``Location`` header
          cannot contain a newline. Worse, ``normalize()`` drops the
          fragment, so the poisoned URL hashed the same as the clean one and
          took its place in deduplication: the clean URL could no longer be
          shortened into a working link at all.
        - ``https://host/x?a=\\x00`` reached PostgreSQL, which refuses NUL in
          text, and the resulting error failed the whole request -- an
          entire batch, when it arrived in one.

        Rejecting rather than stripping: silently storing a different URL
        than the one submitted is its own defect, and a URL that cannot be
        put in a header is not a destination.

        Raises:
            ValidationError: If any C0 control character or DEL is present.
        """
        if any(ord(char) < 32 or ord(char) == 127 for char in self.value):
            raise ValidationError(
                "URL contains control characters", field="url"
            )

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

    def _validate_no_credentials(self, parsed: ParseResult) -> None:
        """
        Reject a URL carrying ``user:password@`` before the host.

        Two reasons, and the second is the load-bearing one:

        - What the victim reads is not where the link goes.
          ``http://www.paypal.com@evil.example/`` shows a trusted name and
          resolves to ``evil.example``; a shortener that admits it lends its
          own domain to the disguise.
        - Everything to the left of ``@`` is opaque to this validator but
          not to the browser. Browsers follow WHATWG and read ``\\`` as a
          separator, so ``http://evil.example\\@public.example/`` is
          ``public.example`` to ``urlparse`` -- the host every check below
          would inspect -- and ``evil.example`` to the browser that
          eventually follows the redirect. No host check can be trusted
          while userinfo is allowed, whatever that check does.

        Raises:
            ValidationError: If the authority contains a userinfo part.
        """
        if "@" in parsed.netloc:
            raise ValidationError(
                "URL must not contain credentials before the host",
                field="url",
            )

    def _validate_bracketed_host_is_an_address(
        self, parsed: ParseResult
    ) -> None:
        """
        Refuse a bracketed authority that does not hold an IPv6 address.

        Brackets exist to wrap an address, and Python also accepts the
        RFC 3986 "IPvFuture" form inside them -- ``v`` followed by hex
        digits, a dot and anything at all. Nothing dereferences that:
        ``new URL()`` refuses it and curl answers "bad range in URL".

        What made it worth refusing rather than ignoring is deduplication.
        ``parsed.hostname`` strips the brackets, so
        ``http://[v1.good.example]/`` was read as the ordinary name
        ``v1.good.example``, hashed identically to
        ``http://v1.good.example/``, and took its short code. Anyone
        shortening the real URL afterwards in the same scope -- and every
        anonymous caller behind one address shares one -- was handed the
        code of a link no browser can open, and the real URL could not be
        shortened into a working one while that row lived. ``v1.``, ``v2.``
        and ``api.v1.`` are ordinary subdomain names, so this is not an
        exotic target.

        Raises:
            ValidationError: If the authority is bracketed and the contents
                are not an IPv6 address.
        """
        if "[" not in parsed.netloc and "]" not in parsed.netloc:
            return

        host = parsed.hostname or ""
        try:
            ipaddress.IPv6Address(host)
        except ValueError:
            raise ValidationError(
                "Brackets in a URL enclose an IPv6 address", field="url"
            )

    def _validate_authority_present(self, parsed: ParseResult) -> None:
        """
        Require an authority, and one whose port can at least be read.

        The one rule that has never moved, which is why it is the one rule
        that also runs on the way out. Every version of this object has
        demanded a host, so no row this service wrote can fail it -- while a
        string with no authority at all cannot be normalized, cannot be
        hashed and cannot be put in a ``Location`` header, so reading it
        back as a URL would only move the failure somewhere less obvious.

        Args:
            parsed: The parsed URL.

        Raises:
            ValidationError: If there is no host, or the port is not a
                number.
        """
        if not parsed.netloc:
            raise ValidationError("URL must have a domain!", field="url")

        try:
            hostname = parsed.hostname
        except ValueError:
            raise ValidationError("Invalid host", field="url")
        if not hostname:
            raise ValidationError("URL must have a hostname", field="url")

        try:
            parsed.port
        except ValueError:
            raise ValidationError("Invalid port number", field="url")

    def _validate_netloc(self, parsed: ParseResult) -> None:
        """Validate the network location (hostname and optional port)."""

        port = parsed.port
        if port is not None and not (1 <= port <= 65535):
            raise ValidationError("Invalid port number", field="url")

        self._validate_host(parsed.hostname)

    def _validate_host(self, host: str) -> None:
        """
        Validate hostname: can be an IP address, 'localhost', or a valid domain.

        For domain names, each label must contain only alphanumeric chars and hyphens,
        cannot start or end with hyphen, and total length ≤ 253. A name written
        in a national script is checked in its punycode form, which is the
        form that actually travels over DNS.
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

        host = self._to_ascii_host(host)

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
            if not LABEL_PATTERN.match(label):
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

    def _validate_public_target(self, parsed: ParseResult) -> None:
        """
        Refuse destinations that only exist inside the deployment's network.

        A shortener is a request forwarder aimed by whoever creates the link
        and fired by whoever opens it. Left open, it hands an anonymous
        caller a link that reads the cloud instance metadata
        (``169.254.169.254``), reaches an admin interface bound to the
        loopback, or sweeps an internal subnet -- from the victim's browser,
        inside the victim's network, under this service's domain.

        The blocklist is applied to the address a resolver would use, not to
        the spelling submitted, because the two differ:
        ``http://0177.0.0.1/`` and ``http://127.1/`` are both the loopback
        to ``inet_aton`` and neither is an address to
        ``ipaddress.ip_address``.

        For the same reason the host is put through UTS-46 *before* it is
        read as an address, and not only before it is read as a name.
        ``http://１２７．０．０．１/`` -- fullwidth digits, fullwidth stops --
        is the loopback to every browser, which maps it exactly as this
        does. Classifying the raw spelling meant the digits were not digits
        and the stops were not separators, so the host was taken for a name,
        matched no reserved suffix and was admitted; ``normalize()`` mapped
        it anyway, so the service hashed the link under ``127.0.0.1`` while
        letting it in. Ideographic and halfwidth stops (U+3002, U+FF61) do
        the same job.

        What this does not cover, and knowingly: a name that resolves to an
        internal address (``127.0.0.1.nip.io``, or any record its owner
        edits after the link is created). Catching that needs resolution at
        redirect time, against the address actually connected to -- a
        different mechanism, in a different layer.

        Raises:
            ValidationError: If the destination is not a public address.
        """
        if self.allow_internal_targets:
            return

        host = self._to_ascii_host(parsed.hostname or "")
        address = self._as_ip_address(host)

        if address is None:
            ascii_host = host.rstrip(".")
            if any(
                ascii_host == suffix or ascii_host.endswith(f".{suffix}")
                for suffix in SPECIAL_USE_SUFFIXES
            ):
                raise ValidationError(
                    "URL must point at a public address", field="url"
                )
            return

        if self._is_internal_address(address):
            raise ValidationError(
                "URL must point at a public address", field="url"
            )

    # ------------------------------------------------------------------
    # Host interpretation helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _to_ascii_host(host: str) -> str:
        """
        Return the host in the ASCII form that travels over DNS.

        An all-ASCII host is returned lowercased and otherwise untouched:
        running it through IDNA would apply rules DNS itself never applied
        to the names already stored under them.

        Args:
            host: Hostname as parsed out of the URL.

        Returns:
            The punycode form for an international name, the host itself
            otherwise.

        Raises:
            ValidationError: If the name cannot be expressed in punycode.
        """
        if host.isascii():
            return host.lower()

        try:
            return idna.encode(host, uts46=True).decode("ascii")
        except (idna.IDNAError, UnicodeError) as exc:
            raise ValidationError(
                f"Invalid international domain name: {exc}", field="url"
            )

    @staticmethod
    def _as_ip_address(host: str) -> Optional[IpAddress]:
        """
        Return the address a resolver would derive from the host, if any.

        Follows the WHATWG URL host parser rather than
        ``ipaddress.ip_address``: a host whose last label is a number is an
        IPv4 address, in however few parts and whatever radix it is written.
        That is what ``inet_aton`` does, what every browser does, and the
        reason a blocklist keyed on the strict spelling of an address is not
        a blocklist at all -- ``0x7f.0.0.1``, ``0177.0.0.1`` and ``127.1``
        all reach the loopback while none of them is an address to Python.

        Args:
            host: Hostname as parsed out of the URL, brackets already
                stripped from IPv6 literals.

        Returns:
            The address, or ``None`` if the host is a name.

        Raises:
            ValidationError: If the host is written as an address and is not
                one. Ambiguity here is not a name: a browser refuses it, so
                admitting it would store a link nobody can open.
        """
        if ":" in host:
            try:
                return ipaddress.IPv6Address(host)
            except ValueError:
                raise ValidationError("Invalid IP address in host", field="url")

        parts = host.split(".")
        if parts[-1] == "":
            parts.pop()  # A single trailing dot is the root, not an empty label
        if not parts or not OriginalUrl._ends_in_number(parts[-1]):
            # Ends in a name, so the host is a name and none of this applies.
            return None
        if len(parts) > 4:
            raise ValidationError("Invalid IP address in host", field="url")

        numbers = [OriginalUrl._parse_ipv4_part(part) for part in parts]
        if any(number is None for number in numbers):
            raise ValidationError("Invalid IP address in host", field="url")
        if any(number > 255 for number in numbers[:-1]):
            raise ValidationError("Invalid IP address in host", field="url")
        # The last part fills every octet the ones before it left out.
        if numbers[-1] >= 256 ** (4 - (len(numbers) - 1)):
            raise ValidationError("Invalid IP address in host", field="url")

        packed = numbers[-1]
        for index, number in enumerate(numbers[:-1]):
            packed += number * 256 ** (3 - index)
        return ipaddress.IPv4Address(packed)

    @staticmethod
    def _ends_in_number(part: str) -> bool:
        """Tell whether the last host label parses as a number."""
        return OriginalUrl._parse_ipv4_part(part) is not None

    @staticmethod
    def _parse_ipv4_part(part: str) -> Optional[int]:
        """
        Parse one dot-separated part of an IPv4 address.

        Radix follows ``inet_aton``: ``0x`` is hexadecimal, a leading zero
        is octal, anything else decimal.

        Args:
            part: One part of the host, between dots.

        Returns:
            Its numeric value, or ``None`` if it is not a number.
        """
        if not part:
            return None

        if part[:2].lower() == "0x":
            digits, radix = part[2:], 16
            if not digits:
                return 0
        elif part[0] == "0" and len(part) > 1:
            digits, radix = part[1:], 8
        else:
            digits, radix = part, 10

        if not _RADIX_DIGITS[radix].match(digits):
            return None
        return int(digits, radix) if digits else 0

    @staticmethod
    def _is_internal_address(address: IpAddress) -> bool:
        """
        Tell whether an address belongs to the deployment's own networks.

        Args:
            address: Address the destination host resolves to literally.

        Returns:
            ``True`` for loopback, private, link-local, multicast, reserved
            and unspecified addresses, including the IPv4 address embedded
            in an IPv4-mapped, 6to4 or Teredo IPv6 address -- those carry a
            v4 destination that the v6 properties alone do not classify.

        ``is_global`` is asked alongside the named properties rather than
        instead of them: it is the one that knows about ranges nobody
        thought to name here, carrier-grade NAT (100.64.0.0/10) among them,
        while the named ones cover what it counts as globally routable
        anyway -- multicast, for one.
        """
        candidates = [address]

        if isinstance(address, ipaddress.IPv6Address):
            embedded = [address.ipv4_mapped, address.sixtofour]
            if address.teredo:
                embedded.extend(address.teredo)
            candidates.extend(item for item in embedded if item is not None)

        return any(
            not candidate.is_global
            or candidate.is_private
            or candidate.is_loopback
            or candidate.is_link_local
            or candidate.is_multicast
            or candidate.is_reserved
            or candidate.is_unspecified
            for candidate in candidates
        )

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------
    def __str__(self) -> str:
        """Return the original URL string."""
        return self.value

    def get_domain(self) -> str:
        """Extract domain (hostname) from the URL."""
        return self._parse().hostname or ""

    def normalize(self) -> str:
        """
        Normalize the URL for consistent comparison and hashing.

        Normalization includes:
        - Lowercase scheme and host.
        - Punycode for an international name, so the two spellings of one
          name deduplicate into one link.
        - Ensure path is at least '/'.
        - Remove fragment.
        - Remove default ports (80 for http, 443 for https).

        The port is dropped from the *parsed* host and not by cutting
        ``':80'`` out of the authority. Cutting the substring reached
        anywhere it appeared, so ``http://[2001:db8::80:1]:80/`` normalized
        to ``http://[2001:db8::1]/`` -- a different host, the same hash and
        therefore the same short code. Within one deduplication scope, and
        every anonymous caller behind one address shares one, that is a link
        pointing where its creator never asked.
        """
        parsed = self._parse()
        scheme = parsed.scheme.lower()
        host = self._to_ascii_host(parsed.hostname or "")
        if ":" in host or "[" in parsed.netloc:
            # An IPv6 literal keeps its brackets -- and so does anything
            # else that arrived inside them. ``parsed.hostname`` strips
            # them, so putting them back only for a host with a colon made
            # ``http://[v1.example.com]/`` normalize onto
            # ``http://v1.example.com/``: two different strings, one hash,
            # one short code. Rows written before brackets were checked on
            # the way in are still read back, and they no longer collide
            # with the name they wrap.
            host = f"[{host}]"

        netloc = host
        port = parsed.port
        if port is not None and DEFAULT_PORTS.get(scheme) != port:
            netloc = f"{netloc}:{port}"

        # Credentials cannot be submitted any more, but rows admitted before
        # that rule carry them, and dropping them here would hash such a row
        # onto the same value as the same address without them.
        userinfo, separator, _ = parsed.netloc.rpartition("@")
        netloc = f"{userinfo}{separator}{netloc}"

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
