def mask_url(url: str) -> str:
    """
    Mask sensitive parts of a URL for logging.

    If the URL is longer than 100 characters, it is truncated to the first 50
    and last 20 characters, separated by ``…``. Otherwise, the URL is returned
    unchanged.

    Args:
        url: The original URL.

    Returns:
        Masked URL string.
    """
    if len(url) > 100:
        return f"{url[:50]}...{url[-20:]}"
    return url
