from dataclasses import dataclass
import re

from link_shortener.domain.exceptions import ValidationError


EMAIL_PATTERN = r"^[^@\s\x1c-\x1f]+@[^@\s\x1c-\x1f]+\.[^@\s\x1c-\x1f]+$"
"""The shape an address must have, for a validator anchored at both ends.

Deliberately loose about what an address may contain -- one ``@``, a dot
in the domain -- and strict about what it may not: whitespace of any kind,
which is what the expression this replaces let through. ``[^@]`` admits a
newline, so ``"user@ex\\nample.com"`` and ``"user@example.com\\n"`` were
both accepted, by this object and by the admin schema built from the same
expression. An address is written into every log line and audit record
about the account and will be written into a mail header once that channel
exists, where a newline is how a header injection is spelled.

``\\x1c-\\x1f`` is spelled out because the two engines disagree about
``\\s``. Python counts the four information separators (FS, GS, RS, US) as
whitespace and the Rust ``regex`` crate, which validates the web schema,
does not -- it reads ``\\s`` as ``\\p{White_Space}``, and those four are
not in it. Measured over U+0000..U+3000: with ``\\s`` alone the schema
accepted exactly those four where this object refused them, so an address
carrying one passed validation and was then refused a layer deeper. They
are the whole disagreement; naming them leaves none.

Spelled with ``$`` for the web schema: the Rust engine does not know
``\\Z``, and its ``$`` already means the end of the text.
``EMAIL_PATTERN_RE`` is the same rule for Python's own engine, which needs
the other anchor.
"""

EMAIL_PATTERN_RE = r"^[^@\s\x1c-\x1f]+@[^@\s\x1c-\x1f]+\.[^@\s\x1c-\x1f]+\Z"
"""``EMAIL_PATTERN`` for ``re``, whose ``$`` is not the end of the text.

Python documents it as matching "at the end of the string or just before
the newline at the end of the string", so ``$`` alone would go on
accepting a trailing newline no matter what the character classes refuse.
``\\Z`` is the end and nothing else. (``\\z``, the spelling that reads
right, arrived after Python 3.12, which is what this runs on.)
"""


@dataclass(frozen=True)
class Email:
    """
    Value object representing an email address.

    Immutable; validates that the string conforms to a basic email format
    (``local-part@domain.tld``) upon creation.

    Attributes:
        value: The email string.
    """
    value: str

    def __post_init__(self):
        """
        Validate the email format immediately after initialisation.

        Raises:
            ValidationError: If the email does not match the expected pattern.
        """
        if not re.match(EMAIL_PATTERN_RE, self.value):
            # The offending value is deliberately left out: this message
            # reaches the client, and the same object is built from database
            # rows, so echoing it would reflect user input and leak stored
            # data on the read path.
            raise ValidationError("Invalid email format", field="email")
    
    def __str__(self) -> str:
        """Return the email string."""
        return self.value
