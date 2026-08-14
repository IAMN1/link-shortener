from typing import List, Optional

from link_shortener.application import (
    RequestContext, DeleteLinkUseCase,
    GetLinkInfoUseCase, GetRecentLinksUseCase
)
from link_shortener.application.use_cases.links.create_short_link import CreateShortLinkUseCase

from link_shortener.domain import LinkNotFoundError


def create_link(
    use_case: CreateShortLinkUseCase, url: str, context: RequestContext, code: Optional[str] = None
) -> dict:
    """
    Create a new short link.

    Args:
        use_case: CreateShortLinkUseCase instance.
        url: The original URL to shorten.
        context: Request context.
        code: Optional custom short code.

    Returns:
        Dictionary with short_code and original_url.

    Raises:
        ValidationError: If the URL or the chosen code is invalid.
        LinkCodeTakenError: If the chosen code is already in use.
    """
    response = use_case.execute(url, context, ttl_seconds=0, custom_code=code)
    return {
        "short_code": response.short_code,
        "original_url": response.original_url,
        "short_url": response.short_url,
        "is_new": response.is_new,
    }


def delete_link(
    use_case: DeleteLinkUseCase, short_code: str, context: RequestContext
) -> bool:
    """
    Delete a short link by its code.

    Ownership is not enforced: the CLI runs as an operator with direct
    access to the database and the configuration, so a permission check
    here would guard nothing that ``psql`` does not already open.

    Args:
        use_case: DeleteLinkUseCase instance.
        short_code: The short code string.
        context: Request context.

    Returns:
        True if deletion was successful, False if link not found or invalid.
    """
    return use_case.execute(short_code, context, enforce_ownership=False)

def get_link_info(
    use_case: GetLinkInfoUseCase, short_code: str, context: RequestContext
) -> Optional[dict]:
    """
    Retrieve basic information about a short link.

    Args:
        use_case: GetLinkInfoUseCase instance.
        short_code: The short code string.
        context: Request context.

    Returns:
        Dictionary with link details or None if not found.
    """
    try:
        response = use_case.execute(short_code, context)

        return {
            "short_code": response.short_code,
            "original_url": response.original_url,
            "clicks": response.clicks,
            "created_at": response.created_at.isoformat(),
            "last_accessed": response.last_accessed.isoformat() 
                if response.last_accessed else None,
        }
    except LinkNotFoundError:
        return None
    except ValueError:
        return None

def list_links(
    use_case: GetRecentLinksUseCase, limit: int, context: RequestContext
) -> List[dict]:
    """
    Return a list of the most recently created links.

    Args:
        use_case: GetRecentLinksUseCase instance.
        limit: Maximum number of links to return.
        context: Request context.

    Returns:
        List of dictionaries, each containing short_code, original_url, clicks, created_at.
    """
    links = use_case.execute(limit, context)
    
    result = [
        {
            "short_code": link.short_code.value,
            "original_url": link.original_url.value,
            "clicks": link.clicks,
            "created_at": link.created_at.isoformat(),
        }
        for link in links
    ]
    
    return result
