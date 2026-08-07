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

    A secret pepper can be provided to increase entropy and prevent predictability.
    The length of the generated code is configurable within min/max bounds.
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

        The pepper (if configured) is appended to the input before hashing.
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
        target_len = max(self.code_length, self.min_length)
        need_bytes = (target_len * 6 + 7) // 8

        hash_bytes = hashlib.sha256(salted.encode("utf-8")).digest()[:need_bytes]
        b64_encoded = base64.urlsafe_b64encode(hash_bytes)
        short_code = b64_encoded.decode("ascii").rstrip("=")[:self.code_length]

        return ShortCode(short_code)

