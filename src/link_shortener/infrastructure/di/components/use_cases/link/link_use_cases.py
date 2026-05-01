from dataclasses import dataclass
from typing import Callable, List

from link_shortener.application import (
    CreateShortLinkUseCase,
    GetLinkInfoUseCase,
    GetExtendedLinkInfoUseCase,
    RedirectLinkUseCase,
    UpdateLinkStatsUseCase,
    DeleteLinkUseCase,
    LinkCache,
    RedirectCache,
    AuditLogger,
    Logger,
    UnitOfWork,
    TaskQueue,
    AuthorizationService,
)
from link_shortener.domain import CodeGenerator, HashCalculator




@dataclass
class LinkUseCasesComponent:
    """
    Holds all dependencies needed by the core link use cases.

    Each factory method returns a fully initialised instance that can be
    used directly by the application layer.
    """

    uow_factory: Callable[[], UnitOfWork]
    cache: LinkCache
    redirect_cache: RedirectCache
    hash_calculator: HashCalculator
    code_generator: CodeGenerator
    base_url: str
    logger: Logger
    audit_logger: AuditLogger
    authz_service: AuthorizationService
    task_queue: TaskQueue
    allowed_schemes: List[str]
    max_collision_attempts: int
    popular_threshold: int
    recent_days: int

    # ----- Creation -----
    def get_create_short_link_use_case(self) -> CreateShortLinkUseCase:
        """
        Return a configured ``CreateShortLinkUseCase``.

        The use case validates the input URL, checks for duplicates via
        cache and DB, generates a unique short code, and persists the new
        link.
        """
        return CreateShortLinkUseCase(
            uow_factory=self.uow_factory,
            cache=self.cache,
            hash_calculator=self.hash_calculator,
            code_generator=self.code_generator,
            base_url=self.base_url,
            logger=self.logger,
            audit_logger=self.audit_logger,
            allowed_schemes=self.allowed_schemes,
            max_collision_attempts=self.max_collision_attempts,
        )

    # ----- Information retrieval -----
    def get_get_link_info_use_case(self) -> GetLinkInfoUseCase:
        """
        Return a configured ``GetLinkInfoUseCase``.

        Retrieves basic information about a link by its short code,
        with cache-first lookup.
        """
        return GetLinkInfoUseCase(
            uow_factory=self.uow_factory,
            cache=self.cache,
            base_url=self.base_url,
            logger=self.logger,
        )

    def get_extended_link_info_use_case(self) -> GetExtendedLinkInfoUseCase:
        """
        Return a configured ``GetExtendedLinkInfoUseCase``.

        Enhances basic link information with derived metrics such as
        popularity, age, and clicks per day.
        """
        return GetExtendedLinkInfoUseCase(
            uow_factory=self.uow_factory,
            cache=self.cache,
            base_url=self.base_url,
            logger=self.logger,
            popular_threshold=self.popular_threshold,
            recent_days=self.recent_days,
        )

    # ----- Redirect and stats update -----
    def get_redirect_link_use_case(self) -> RedirectLinkUseCase:
        """
        Return a configured ``RedirectLinkUseCase``.

        Resolves a short code to the original URL using a multi-level cache
        and enqueues a background task to update click statistics.
        """
        return RedirectLinkUseCase(
            uow_factory=self.uow_factory,
            link_cache=self.cache,
            redirect_cache=self.redirect_cache,
            logger=self.logger,
            audit_logger=self.audit_logger,
            task_queue=self.task_queue,
        )

    def get_update_link_stats_use_case(self) -> UpdateLinkStatsUseCase:
        """
        Return a configured ``UpdateLinkStatsUseCase``.

        Designed to be called asynchronously by a worker; increments click
        counts and refreshes the link cache.
        """
        return UpdateLinkStatsUseCase(
            uow_factory=self.uow_factory,
            link_cache=self.cache,
            logger=self.logger,
        )

    # ----- Deletion -----
    def get_delete_link_use_case(self) -> DeleteLinkUseCase:
        """
        Return a configured ``DeleteLinkUseCase``.

        Deletes a link by its short code after verifying the caller has the
        ``link:delete`` permission.
        """
        return DeleteLinkUseCase(
            uow_factory=self.uow_factory,
            logger=self.logger,
            audit_logger=self.audit_logger,
            authz=self.authz_service,
        )
