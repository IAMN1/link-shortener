from dataclasses import dataclass
import re

from link_shortener.domain.exceptions import ValidationError
from link_shortener.domain.i18n import N_


EMAIL_PATTERN = r"^[^@\s\x1c-\x1f]+@[^@\s\x1c-\x1f]+\.[^@\s\x1c-\x1f]+$"
"""The shape an address must have, for a validator anchored at both ends.

Deliberately loose about what an address may contain -- one ``@``, a dot
in the domain -- and strict about what it may not: whitespace of any kind,
which is what the expression this replaces let through. ``[^@]`` admits a
newline, so ``"user@ex\\nample.com"`` and ``"user@example.com\\n"`` were
both accepted, by this object and by the admin schema built from the same
expression. An address is written into every log line and audit record
about the account, and into the ``To`` header of the mail this service now
sends, where a newline is how a header injection is spelled.

``\\x1c-\\x1f`` is spelled out because the two engines disagree about
``\\s``. Python counts the four information separators (FS, GS, RS, US) as
whitespace and the Rust ``regex`` crate, which validates the web schema,
does not -- it reads ``\\s`` as ``\\p{White_Space}``, and those four are
not in it. With ``\\s`` alone the schema accepts exactly those four where
this object refuses them, so an address carrying one passes validation and
is refused a layer deeper. Over U+0000..U+3000 they are the whole
disagreement; naming them leaves none.

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


MAX_EMAIL_LENGTH = 254
"""The longest an address may be, in characters.

RFC 5321 section 4.5.3.1.3 caps a forward-path at 256 octets, and a path
is written ``<address>`` -- so the address inside it has 254. The local
part is capped at 64 by section 4.5.3.1.1, which this does not check
separately: an address that passes both halves passes this one, and the
whole-path limit is the one a receiving host actually enforces.

Not decoration, and not a tidier document. Without it an address of any
length reached ``users.email``, which is ``String(255)``: PostgreSQL
refused the insert, the refusal is not a ``ValidationError``, and no
handler on the way out knew it -- so an **unauthenticated** two-field
body to ``POST /api/v1/auth/register`` answered ``500``. Measured on the
production profile with a 261-character address. SQLite does not
reproduce it: it ignores a declared width, so the suite running on SQLite
saw the row stored and nothing wrong.

254 rather than 255 leaves the column a character it can never need,
which is the right way round: the rule is the standard's, and the column
is wide enough to hold whatever the rule admits.

This is the same shape of defect as the one ``Link.create`` records for
``ttl_seconds`` -- a value the domain did not bound, refused instead by
arithmetic or by a column, and reported as a fault of the service.
"""


@dataclass(frozen=True)
class Email:
    """
    Value object representing an email address.

    Immutable; validates that the string conforms to a basic email format
    (``local-part@domain.tld``) upon creation, and holds it in lower case.

    The lowering is what makes an address name one account. Without it
    ``find_by_email`` compared strings, the unique index on ``users.email``
    saw two different ones, and registering ``Case@Example.com`` over an
    existing ``case@example.com`` created a second account for the same
    mailbox: two confirmation links, either of which could be opened, and
    a sign-in that depended on which capitalisation was typed.

    RFC 5321 section 2.4 puts the price plainly. Domains "follow normal
    DNS rules and are hence not case sensitive", so lowering that half
    costs nothing. The other half it reserves: "The local-part of a
    mailbox MUST BE treated as case sensitive. Therefore, SMTP
    implementations MUST take care to preserve the case of mailbox
    local-parts." A host that distinguishes ``Smith`` from ``smith`` would
    therefore receive mail addressed to somebody else. The same paragraph
    goes on: "However, exploiting the case sensitivity of mailbox
    local-parts impedes interoperability and is discouraged", and no mail
    provider in ordinary use does so -- which is the trade being made
    here, deliberately and in one direction: one account per mailbox,
    bought with a rule the standard leaves to the receiving host.

    Django lowers only the domain for this reason (``normalize_email``:
    "Normalize the email address by lowercasing the domain part of it"),
    and keeps the ambiguity this object exists to remove.

    Whitespace is not stripped, only case is changed. Trimming would
    quietly accept the trailing newline the pattern above refuses on
    purpose -- an address goes into a mail header, and a newline in a
    header is an injection.

    Attributes:
        value: The email string, lower case.
    """
    value: str

    def __post_init__(self):
        """
        Validate the email format, then lower it.

        Validated before it is lowered so that what is judged is what the
        caller sent; the pattern is indifferent to case, so the order
        changes no verdict.

        Raises:
            ValidationError: If the email does not match the expected pattern.
        """
        # Length before shape, and not for speed: the pattern is anchored
        # and linear, so a long string costs little to match. It is that a
        # 300-character address and a 300-character line of noise are the
        # same fault, and the caller is better told which limit it met.
        if len(self.value) > MAX_EMAIL_LENGTH:
            # No length in the message and no value: the same reasoning as
            # below -- this sentence reaches the client, and the object is
            # also built from stored rows.
            raise ValidationError(
                N_("Email address is too long"), field="email"
            )

        if not re.match(EMAIL_PATTERN_RE, self.value):
            # The offending value is deliberately left out: this message
            # reaches the client, and the same object is built from database
            # rows, so echoing it would reflect user input and leak stored
            # data on the read path.
            raise ValidationError(N_("Invalid email format"), field="email")

        # object.__setattr__ because the dataclass is frozen. That call
        # would bypass frozen anywhere; what makes here the right place is
        # that the instance is not finished yet, so nothing has read the
        # old value. Normalising in the callers instead would leave each
        # of them responsible for remembering to.
        object.__setattr__(self, "value", self.normalise(self.value))

    @staticmethod
    def normalise(value: str) -> str:
        """
        Return the form an address is stored, compared and looked up in.

        The rule itself, in one place. Everything that has to ask "is
        this row normalised?" or "what would it become?" -- the
        repository, the maintenance command -- asks here rather than
        lowering a string of its own, so the answer cannot drift from
        what this object does on the way in.

        Args:
            value: An address, as typed or as stored.

        Returns:
            The normalised form of it.
        """
        return value.lower()

    @classmethod
    def from_storage(cls, value: str) -> "Email":
        """
        Rebuild an address from a stored row without normalising it.

        Lowering belongs to the way in, where an address is typed. A row
        is not an input: it is what a previous way in already produced,
        and lowering it a second time changes data rather than cleaning
        it. Rows written before this rule exists are the ones that feel
        the difference -- reconstructed as they are, they are written
        back as they are.

        That mattered twice over. Copying the lowered form back rewrote
        such a row in place, outside ``flask maintenance
        normalize-emails`` and outside any log; and where another account
        already held the lower-case form it hit the unique index instead
        -- on confirmation that means ``IntegrityError``, answered as 500,
        with the token left unspent, so the account could never be
        confirmed at all.

        The address is still validated: a row that could not be an
        address is a broken row whichever way it got there.

        Args:
            value: The address exactly as the database holds it.

        Returns:
            An ``Email`` holding that exact string.

        Raises:
            ValidationError: If the stored value is not an address.
        """
        # Built through the normal constructor first, so the row goes
        # through the same validation as an input, then set back to what
        # was stored. The instance has not left this method yet, which is
        # what makes writing to a frozen dataclass acceptable here -- the
        # same reasoning ``__post_init__`` uses one method above.
        email = cls(value)
        object.__setattr__(email, "value", value)
        return email

    def __str__(self) -> str:
        """Return the email string."""
        return self.value
