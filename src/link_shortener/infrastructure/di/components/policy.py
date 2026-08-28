from typing import Optional
from link_shortener.domain import HashCalculator, CodeGenerator
from link_shortener.infrastructure.policies.base64_url_code_generator import Base64UrlCodeGenerator
from link_shortener.infrastructure.policies.sha256_hash_calculator import SHA256HashCalculator

class PolicyComponent:
    """
    Supplies the application with concrete domain policy objects.

    Both the hash calculator and the code generator are created lazily
    and cached for the lifetime of the application.
    """
    def __init__(self, code_length: int, min_length: int, max_length: int, pepper: str):
        """
        Args:
            code_length: Desired length of generated short codes.
            min_length: Minimum allowed length.
            max_length: Maximum allowed length.
            pepper: Secret pepper added before hashing to prevent
                predictability.
        """
        self.code_length = code_length
        self.min_length = min_length
        self.max_length = max_length
        self.pepper = pepper

        # Annotated Optional rather than inferred from this assignment: the
        # attribute holds None until the first call builds it, and a checker
        # told otherwise reports both the assignment and the return as errors.
        self._hash_caclculator: Optional[HashCalculator] = None
        self._code_generator: Optional[CodeGenerator] = None

    def get_hash_calculator(self) -> HashCalculator:
        """
        Return a SHA-256 based hash calculator.

        The calculator produces a deterministic 64-character hex digest
        of a normalised URL.
        """
        if self._hash_caclculator is None:
            self._hash_caclculator = SHA256HashCalculator()
        return self._hash_caclculator

    def get_code_generator(self) -> CodeGenerator:
        """
        Return a Base64URL code generator with the configured length and
        pepper.

        The generator uses SHA-256 internally and encodes the result in
        URL-safe Base64.
        """
        if self._code_generator is None:
            self._code_generator = Base64UrlCodeGenerator(
                code_length=self.code_length,
                min_length=self.min_length,
                max_length=self.max_length,
                pepper=self.pepper,
            )
        return self._code_generator
