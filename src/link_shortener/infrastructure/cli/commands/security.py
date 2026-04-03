import secrets


def generate_secrets() -> dict[str, str]:
    """
    Generate new secure random values for SECRET_KEY and SHORT_CODE_PEPPER.

    Returns:
        Dictionary with keys 'SECRET_KEY' and 'SHORT_CODE_PEPPER'.
    """
    return {
        "SECRET_KEY": secrets.token_hex(32),
        "SHORT_CODE_PEPPER": secrets.token_hex(32),
    }
