from dataclasses import dataclass

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.link import ShortLinkResponse
from link_shortener.application.dtos.user_activity import UserActivityResponse
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.use_cases.base_use_case import BaseUseCase


@dataclass
class GetUserActivityStatsUseCase(BaseUseCase):
    """
    Retrieve activity statistics for a specific user.

    Access is restricted: only the user themselves or an administrator
    (with ``admin:view_users``) can view the statistics.
    """
    uow_factory: UnitOfWorkFactory
    base_url: str

    def execute(self, user_id: str, context: RequestContext) -> UserActivityResponse:
        """
        Execute the use case.

        Args:
            user_id: UUID of the user whose stats are requested.
            context: Request context with current user info.

        Returns:
            UserActivityResponse containing total links, total clicks,
            average clicks per link, and the 10 most recent links.

        Raises:
            DomainError: If the caller is not authorized.
        """

        # Authorization: admin or the user themselves
        with self.uow_factory(read_only=True) as uow:
            stats = uow.links.get_user_stats(user_id)

        avg = (stats["total_clicks"] / stats["total_links"]) if stats["total_links"] else 0.0
        recent = [ShortLinkResponse.from_link(link, self.base_url) for link in stats["recent_links"]]
        return UserActivityResponse(
            user_id=user_id,
            total_links=stats["total_links"],
            total_clicks=stats["total_clicks"],
            avg_clicks_per_link=round(avg, 2),
            recent_links=recent,
        )
