from dataclasses import dataclass
from typing import List

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.link import ShortLinkResponse
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.use_cases.base_use_case import BaseUseCase


@dataclass
class GetUserLinksUseCase(BaseUseCase):
    """
    Retrieve short links owned by a specific user.

    Attributes:
        uow_factory: Callable that returns a new Unit of Work instance.
        base_url: Base URL of the service for constructing short URLs.
    """
    uow_factory: UnitOfWorkFactory
    base_url: str

    def execute(
        self,
        user_id: str,
        context: RequestContext,
        offset: int = 0,
        limit: int = 50,
    ) -> List[ShortLinkResponse]:
        """
        Fetch links belonging to the user with pagination.

        Args:
            user_id: UUID of the user whose links are requested.
            context: Request context (not used for authorisation here,
                authorisation is handled by the caller / decorator).
            offset: Number of links to skip (default 0).
            limit: Maximum number of links to return (default 50, max 200).

        Returns:
            List of ``ShortLinkResponse`` DTOs; may be empty if the user
            has no links.
        """
        limit = min(limit, 200)
        with self.uow_factory(read_only=True) as uow:
            links = uow.links.find_by_owner(user_id, offset=offset, limit=limit)
        return [ShortLinkResponse.from_link(link, self.base_url) for link in links]
