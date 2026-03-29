from datetime import datetime, timezone, timedelta
from link_shortener.domain.repositories.link_repository import LinkRepository


def clean_expired_links(repository: LinkRepository, days: int = 30) -> int:
    """
    Delete links that have not been accessed for more than `days` days.

    Args:
        repository: LinkRepository instance.
        days: Age threshold in days (links older than this are deleted).

    Returns:
        Number of deleted links.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return repository.delete_unaccessed_before(cutoff=cutoff)