"""
Component that produces fully configured core link use cases.

This module defines the ``LinkUseCasesComponent`` dataclass which aggregates
all infrastructure dependencies required by link-related use cases and
exposes factory methods for creating them.
"""

from dataclasses import dataclass
from typing import List

from link_shortener.application import (
    ServiceCache,
    UnitOfWorkFactory, CreateShortLinkUseCase,
    DeleteLinkUseCase, GetExtendedLinkInfoUseCase, GetLinkInfoUseCase,
    GetUserLinksUseCase, RedirectLinkUseCase, UpdateLinkStatsUseCase,
    AuditLogger, Logger, RedirectCache, TaskQueue
)
from link_shortener.application.ports.auth.authorization_service import (
    AuthorizationService,
)
from link_shortener.domain import CodeGenerator, HashCalculator


@dataclass
class LinkUseCasesComponent:
    """Holds all dependencies needed by the core link use cases.

    Each factory method returns a fully initialised instance that can be
    used directly by the application layer.

    Attributes:
        uow_factory: Factory for creating Unit of Work instances.
        cache: Full link cache (L2) implementation.
        redirect_cache: Fast redirect cache (L1) implementation.
        hash_calculator: Strategy for computing URL hashes.
        code_generator: Strategy for generating short codes.
        base_url: Base URL of the service for constructing short URLs.
        logger: Application logger.
        audit_logger: Audit logger for security-relevant events.
        task_queue: Asynchronous task queue for offloading work.
        allowed_schemes: URL schemes permitted for shortening.
        max_url_length: Longest URL admitted, from ``MAX_URL_LENGTH``.
        allow_internal_targets: Whether destinations inside the
            deployment's own network are admitted.
        max_collision_attempts: Max retries for code generation on collision.
        popular_threshold: Click threshold for a link to be considered popular.
        recent_days: Number of days to consider a link as recent.
        guest_link_limit: Max guest links allowed in a given window.
        guest_link_window_days: Time window (days) for guest link counting.
        default_guest_ttl_seconds: TTL applied to guest-created links, and
            the most a guest may ask for.
        max_ttl_seconds: Longest lifetime any caller may ask for.
        authorization_service: Service that answers permission questions.
    """

    uow_factory: UnitOfWorkFactory
    cache: ServiceCache
    redirect_cache: RedirectCache
    hash_calculator: HashCalculator
    code_generator: CodeGenerator
    base_url: str
    logger: Logger
    audit_logger: AuditLogger
    task_queue: TaskQueue
    allowed_schemes: List[str]
    max_url_length: int
    allow_internal_targets: bool
    max_collision_attempts: int
    popular_threshold: int
    recent_days: int
    guest_link_limit: int
    guest_link_window_days: int
    default_guest_ttl_seconds: int
    max_ttl_seconds: int
    authorization_service: AuthorizationService

    # ------------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------------
    def get_create_short_link_use_case(self) -> CreateShortLinkUseCase:
        """Return a configured ``CreateShortLinkUseCase``.

        The use case validates the input URL, checks for duplicates via
        cache and database, generates a unique short code, and persists the
        new link.

        Returns:
            A ready-to-use ``CreateShortLinkUseCase`` instance.
        """
        return CreateShortLinkUseCase(
            uow_factory=self.uow_factory,
            cache=self.cache,
            stats_cache=self.cache,
            hash_calculator=self.hash_calculator,
            code_generator=self.code_generator,
            base_url=self.base_url,
            logger=self.logger,
            audit_logger=self.audit_logger,
            allowed_schemes=self.allowed_schemes,
            max_url_length=self.max_url_length,
            allow_internal_targets=self.allow_internal_targets,
            max_collision_attempts=self.max_collision_attempts,
            guest_link_limit=self.guest_link_limit,
            guest_link_window_days=self.guest_link_window_days,
            default_guest_ttl_seconds=self.default_guest_ttl_seconds,
            max_ttl_seconds=self.max_ttl_seconds,
        )

    # ------------------------------------------------------------------
    # Information retrieval
    # ------------------------------------------------------------------
    def get_get_link_info_use_case(self) -> GetLinkInfoUseCase:
        """Return a configured ``GetLinkInfoUseCase``.

        Retrieves basic information about a link by its short code from the
        repository. Takes no cache: it neither reads nor writes one.

        Returns:
            A ready-to-use ``GetLinkInfoUseCase`` instance.
        """
        return GetLinkInfoUseCase(
            uow_factory=self.uow_factory,
            base_url=self.base_url,
            logger=self.logger,
        )

    def get_extended_link_info_use_case(self) -> GetExtendedLinkInfoUseCase:
        """Return a configured ``GetExtendedLinkInfoUseCase``.

        Enhances basic link information with derived metrics such as
        popularity, age, and clicks per day.

        Returns:
            A ready-to-use ``GetExtendedLinkInfoUseCase`` instance.
        """
        return GetExtendedLinkInfoUseCase(
            uow_factory=self.uow_factory,
            base_url=self.base_url,
            logger=self.logger,
            popular_threshold=self.popular_threshold,
            recent_days=self.recent_days,
        )

    # ------------------------------------------------------------------
    # Redirect and stats update
    # ------------------------------------------------------------------
    def get_redirect_link_use_case(self) -> RedirectLinkUseCase:
        """Return a configured ``RedirectLinkUseCase``.

        Resolves a short code to the original URL using a multi-level cache
        and enqueues a background task to update click statistics.

        Returns:
            A ready-to-use ``RedirectLinkUseCase`` instance.
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
        """Return a configured ``UpdateLinkStatsUseCase``.

        Designed to be called asynchronously (e.g. by a Celery worker);
        increments click counts. Takes no cache: writing one here brought
        deleted links back to life.

        Returns:
            A ready-to-use ``UpdateLinkStatsUseCase`` instance.
        """
        return UpdateLinkStatsUseCase(
            uow_factory=self.uow_factory,
            logger=self.logger,
        )

    # ------------------------------------------------------------------
    # Deletion
    # ------------------------------------------------------------------
    def get_delete_link_use_case(self) -> DeleteLinkUseCase:
        """Return a configured ``DeleteLinkUseCase``.

        Deletes a link by its short code after verifying the caller has the
        required permissions.

        Returns:
            A ready-to-use ``DeleteLinkUseCase`` instance.
        """
        return DeleteLinkUseCase(
            uow_factory=self.uow_factory,
            cache=self.cache,
            redirect_cache=self.redirect_cache,
            stats_cache=self.cache,
            logger=self.logger,
            audit_logger=self.audit_logger,
            authorization_service=self.authorization_service,
        )

    def get_get_user_links_use_case(self) -> GetUserLinksUseCase:
        """Return a configured ``GetUserLinksUseCase``.

        Retrieves all short links owned by a specific user.

        Returns:
            A ready-to-use ``GetUserLinksUseCase`` instance.
        """
        return GetUserLinksUseCase(
            uow_factory=self.uow_factory,
            base_url=self.base_url,
        )
