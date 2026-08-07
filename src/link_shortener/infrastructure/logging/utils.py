import logging


def _standard_record_attrs() -> frozenset:
    """
    Return the attribute names every ``LogRecord`` carries by itself.

    Derived from a throwaway record rather than typed out, because the set
    grows between Python releases and a hand-written list silently falls
    behind. It did: 3.12 added ``taskName``, which neither formatter knew
    about, so every console line ended in ``[taskName=None]`` and every JSON
    line carried ``"taskName": null``.

    ``message`` and ``asctime`` are added by ``logging`` during formatting
    rather than at construction, so they are named explicitly.

    Returns:
        Names that belong to the logging machinery, not to the caller.
    """
    reference = logging.LogRecord(
        name="", level=logging.INFO, pathname="", lineno=0,
        msg="", args=(), exc_info=None,
    )
    return frozenset(reference.__dict__) | {"message", "asctime"}


STANDARD_RECORD_ATTRS = _standard_record_attrs()
"""Attributes a formatter must not mistake for application-supplied fields."""


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
