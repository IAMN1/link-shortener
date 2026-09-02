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

    Who may ask about whom is decided by the two routes that reach this,
    and deliberately not here. ``GET /api/v1/stats/mine`` holds
    ``link:view_own`` and passes the caller's own id, which it takes from
    the request rather than from the query -- there is no way to name
    somebody else through it. ``GET /api/v1/admin/users/<id>/stats`` takes
    the id from the address and holds ``admin:view_users``.

    The check is not moved in here the way ``ReadJournalUseCase`` and
    ``GetSecurityCountsUseCase`` moved theirs. Those two have a caller
    that reaches them without passing a decorator -- the CLI -- and this
    one has none; the account whose statistics these are is an argument,
    not a row this use case loads, so there is nothing here that a route
    does not already know. What that costs is written down: the guarantee
    lives in two places rather than one, and a route that started taking
    the id from the query would be the whole of the defect. A test holds
    ``/stats/mine`` to answering about its caller.
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
        """
        with self.uow_factory(read_only=True) as uow:
            stats = uow.links.get_user_stats(user_id)

        avg = (stats.total_clicks / stats.total_links) if stats.total_links else 0.0
        recent = [
            ShortLinkResponse.from_link(link, self.base_url)
            for link in stats.recent_links
        ]
        return UserActivityResponse(
            user_id=user_id,
            total_links=stats.total_links,
            total_clicks=stats.total_clicks,
            avg_clicks_per_link=round(avg, 2),
            recent_links=recent,
        )
