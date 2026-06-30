from dataclasses import dataclass, field
from typing import List

from link_shortener.application.dtos.link import ShortLinkResponse


@dataclass
class UserActivityResponse:
    """
    Aggregated activity statistics for a specific user.

    Attributes:
        user_id: Unique identifier of the user.
        total_links: Total number of short links owned by the user.
        total_clicks: Sum of clicks across all user's links.
        avg_clicks_per_link: Average clicks per link (0.0 if no links).
        recent_links: Up to 10 most recently created links by the user.
    """
    user_id: str
    total_links: int
    total_clicks: int
    avg_clicks_per_link: float = 0.0
    recent_links: List[ShortLinkResponse] = field(default_factory=list)
