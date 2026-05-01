"""
URL building utilities.

This module contains pure functions for constructing URLs used across the application.
They belong to the Application layer because they are infrastructure‑independent helpers.
"""

def build_short_url(base_url: str, short_code: str) -> str:
    """
    Build a full short URL from base URL and short code.

    Ensures exactly one slash between base URL and short code,
    regardless of whether base_url already ends with a slash.

    Args:
        base_url: Base URL of the service (e.g., "https://short.xyz" or "https://short.xyz/").
        short_code: The short code string (e.g., "abc123").

    Returns:
        Full short URL string.

    Raises:
        ValueError: If base_url or short_code is empty.
    """
    if not base_url:
        raise ValueError("base_url must not be empty")
    if not short_code:
        raise ValueError("short_code must not be empty")
    return f"{base_url.rstrip('/')}/{short_code}"
