"""Abstract interface for generating a short code from an input string."""

import uuid
from abc import ABC, abstractmethod

from link_shortener.domain.value_objects.original_url import OriginalUrl
from link_shortener.domain.value_objects.short_code import ShortCode


class CodeGenerator(ABC):
    """
    Domain policy for generating a short code from a given input string.

    The input string is typically a normalized URL. The generated code must
    satisfy the format constraints defined by the ShortCode value object
    (length, allowed characters). Implementations may use hashing, random
    generation, or other algorithms.

    This abstraction belongs to the domain layer; concrete implementations
    reside in the infrastructure layer.
    """

    @abstractmethod
    def generate(self, input_str: str) -> ShortCode:
        """
        Generate a short code from an arbitrary input string.

        Args:
            input_str: The string to base the code on (e.g., normalized URL).

        Returns:
            ShortCode: A value object containing the generated short code.
        """
        raise NotImplementedError
    
    def generate_for_url(self, original_url: OriginalUrl) -> ShortCode:
        """
        Convenience method: generate a short code directly from an ``OriginalUrl``.

        Uses the normalized string representation of the URL as input.

        Args:
            original_url: The original URL value object.

        Returns:
            ShortCode: The generated short code.
        """
        return self.generate(original_url.normalize())
    
    def generate_unique(self, original_url: OriginalUrl, attempt: int) -> ShortCode:
        """
        Generate a code with an optional salt to resolve collisions.

        When ``attempt > 0``, a suffix is appended to the normalized URL before
        passing it to ``generate()``. This allows creating different codes for
        the same original URL when the desired code is already taken.

        Args:
            original_url: The original URL value object.
            attempt: Collision attempt counter (0 = no salt).

        Returns:
            ShortCode: A (potentially different) short code
        """
        base = original_url.normalize()
        if attempt == 0:
            return self.generate(base)
        salted = f"{base}#collision_{attempt}"
        return self.generate(salted)

    def generate_fresh(self, original_url: OriginalUrl) -> ShortCode:
        """
        Generate a code for a URL whose deterministic codes are all taken.

        ``generate_unique`` is a pure function of the URL and the attempt
        number, so a URL has exactly as many codes as there are attempts --
        five, service-wide, for all time. That ceiling was invisible while a
        URL could only ever have one link: deduplication matched on the URL
        alone. It is not invisible now. Links deduplicate per owner and
        expired ones are skipped, so one URL legitimately needs a code per
        owner and another after each expiry, and the sixth caller ran into a
        failure no retry could clear -- the URL became unshortenable for
        everybody, permanently.

        Entropy is what removes the ceiling. The code is still derived from
        the URL; a nonce merely makes the supply unbounded.

        Args:
            original_url: The original URL value object.

        Returns:
            ShortCode: A code unrelated to any previously issued one.
        """
        return self.generate(
            f"{original_url.normalize()}#fresh_{uuid.uuid4().hex}"
        )
