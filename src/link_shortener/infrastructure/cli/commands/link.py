from typing import List, Optional
from link_shortener.domain.repositories.link_repository import LinkRepository
from link_shortener.domain.value_objects.short_code import ShortCode


def delete_link(repository: LinkRepository, short_code: str) -> bool:
    """
    Delete a short link by its code.

    Args:
        repository: LinkRepository instance.
        short_code: Short code string (will be validated).

    Returns:
        True if deletion was successful, False if link not found or code invalid.
    """
    try:
        code = ShortCode(short_code)
        return repository.delete(code)
    except ValueError:
        print(f"Invalid short code format: {short_code}")
        return False

def get_link_info(repository: LinkRepository, short_code: str) -> Optional[dict]:
    """
    Retrieve detailed information about a short link.

    Args:
        repository: LinkRepository instance.
        short_code: Short code string.

    Returns:
        Dictionary with link details, or None if not found or invalid.
    """
    try:
        code = ShortCode(short_code)
        link = repository.find_by_code(code)
        if not link:
            return None
        return {
            "short_code": link.short_code.value,
            "original_url": link.original_url.value,
            "clicks": link.clicks,
            "created_at": link.created_at.isoformat(),
            "last_accessed": link.last_accessed.isoformat() if link.last_accessed else None,
        }
    except ValueError:
        return None

def list_links(repository: LinkRepository, limit: int = 10) -> List[dict]:
    """
    Return a list of the most recently created links.

    Args:
        repository: LinkRepository instance.
        limit: Maximum number of links to return.

    Returns:
        List of dictionaries, each containing short_code, original_url, clicks, created_at.
    """
    links = repository.get_recent(limit)
    result = []
    for link in links:
        result.append({
            "short_code": link.short_code.value,
            "original_url": link.original_url.value,
            "clicks": link.clicks,
            "created_at": link.created_at.isoformat(),
        })
    return result