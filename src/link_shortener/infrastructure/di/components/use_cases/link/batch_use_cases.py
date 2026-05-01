from dataclasses import dataclass
from typing import Callable, List

from link_shortener.application import (
    BatchCreateLinksUseCase,
    BatchLinkCreator,
    BatchLinkFetcher,
    UrlGrouper,
    BatchResponseBuilder,
    LinkCache,
    AuditLogger,
    Logger,
    UnitOfWork,
)
from link_shortener.domain import CodeGenerator, HashCalculator


@dataclass
class BatchUseCasesComponent:
    """
    Provides the fully configured ``BatchCreateLinksUseCase``.

    All dependencies are injected at construction time; the component then
    builds the inner helper objects and wires them together.
    """

    uow_factory: Callable[[], UnitOfWork]
    cache: LinkCache
    hash_calculator: HashCalculator
    code_generator: CodeGenerator
    base_url: str
    logger: Logger
    audit_logger: AuditLogger
    allowed_schemes: List[str]
    max_collision_attempts: int
    batch_limit: int

    def get_batch_create_links_use_case(self) -> BatchCreateLinksUseCase:
        """
        Return a fully initialised ``BatchCreateLinksUseCase``.

        The use case coordinates four inner components:
        - ``UrlGrouper`` – validates, normalises, and groups input URLs.
        - ``BatchLinkFetcher`` – checks cache and DB for existing links.
        - ``BatchLinkCreator`` – generates new short codes with collision
          resolution.
        - ``BatchResponseBuilder`` – builds response DTOs for newly created
          links.
        """
        grouper = UrlGrouper(
            allowed_schemes=self.allowed_schemes,
            hash_calculator=self.hash_calculator,
            logger=self.logger,
        )
        fetcher = BatchLinkFetcher(cache=self.cache)
        creator = BatchLinkCreator(
            code_generator=self.code_generator,
            logger=self.logger,
            max_attempts=self.max_collision_attempts,
        )
        builder = BatchResponseBuilder()

        return BatchCreateLinksUseCase(
            uow_factory=self.uow_factory,
            cache=self.cache,
            base_url=self.base_url,
            logger=self.logger,
            audit_logger=self.audit_logger,
            batch_limit=self.batch_limit,
            grouper=grouper,
            fetcher=fetcher,
            creator=creator,
            builder=builder,
        )
