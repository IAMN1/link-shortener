"""
Base64URL-encoded SHA-256 code generator
with configurable length and pepper.
"""

import base64
import hashlib

from link_shortener.domain import CodeGenerator, ShortCode


class Base64UrlCodeGenerator(CodeGenerator):
    """
    Generates a short code by hashing the input string with SHA-256 and encoding
    the result in URL-safe Base64.

    A secret pepper is required and is appended to every input before
    hashing. It adds no entropy -- a fixed string cannot -- and that is
    not what it is for: without it the code for any address is
    ``sha256(url)``, which anybody can compute, so a caller could tell
    whether a URL had been shortened here by asking for the code it would
    get. The length of the generated code is configurable within min/max
    bounds.
    """

    def __init__(self,
        code_length: int,
        min_length: int,
        max_length: int,
        pepper: str
    ):
        """
        Args:
            code_length: Desired length of the short code.
            min_length: Minimum allowed length.
            max_length: Maximum allowed length.
            pepper: Secret string added to input before hashing.

        Raises:
            ValueError: If ``code_length`` is outside ``[min_length, max_length]``.
        """

        if not (min_length <= code_length <= max_length):
            raise ValueError(
                f"code_length must be between {min_length} and {max_length}"
            )

        self.code_length = code_length
        self.min_length = min_length
        self.max_length = max_length
        self.pepper = pepper

    def generate(self, input_str: str) -> ShortCode:
        """
        Generate a short code from the input string using SHA-256 and Base64URL.

        The pepper is appended to the input before hashing -- always, it
        is a required argument and there is no branch that skips it.
        The resulting hash is truncated to the required number of bytes,
        Base64URL-encoded, and trimmed to `code_length` characters.

        Args:
            input_str: The string to base the code on (e.g., normalized URL).

        Returns:
            ShortCode value object containing the generated code.
        """
        salted = input_str + self.pepper

        # Determine how many bytes of hash are needed to produce a Base64 string
        # of at least `code_length` characters (each Base64 char represents 6 bits).
        # The constructor refuses anything outside
        # ``min_length <= code_length <= max_length``, so this is
        # ``code_length``; the ``max`` is kept as the statement of what the
        # arithmetic below needs rather than as a live choice.
        target_len = max(self.code_length, self.min_length)
        need_bytes = (target_len * 6 + 7) // 8

        hash_bytes = hashlib.sha256(salted.encode("utf-8")).digest()[:need_bytes]
        b64_encoded = base64.urlsafe_b64encode(hash_bytes)
        short_code = b64_encoded.decode("ascii").rstrip("=")[:self.code_length]

        return ShortCode(short_code)
