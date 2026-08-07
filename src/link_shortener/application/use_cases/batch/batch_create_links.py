from dataclasses import dataclass

import time
from typing import Callable, List, Optional, Tuple
import uuid

from link_shortener.application.dtos.batch import BatchCreateResponse, BatchItemResponse
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.context import RequestContext

from link_shortener.application.ports.cache.link_cache import LinkCache
from link_shortener.application.ports.cache.link_service_stats_cache import (
    StatsCache,
)
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.application.use_cases.batch.creator import BatchLinkCreator
from link_shortener.application.use_cases.batch.fetcher import BatchLinkFetcher
from link_shortener.application.use_cases.batch.grouper import UrlGrouper
from link_shortener.application.use_cases.batch.response_builder import BatchResponseBuilder
from link_shortener.domain.exceptions import (
    GuestLinkLimitExceededError, LinkConflictError, ValidationError
)
from link_shortener.domain.value_objects.dedup_scope import DedupScope
from link_shortener.domain.value_objects.owner_id import OwnerID


@dataclass
class BatchCreateLinksUseCase(BaseUseCase):
    """
    Orchestrates the batch creation of short links.

    Delegates to specialised components:
    - UrlGrouper: validates and groups URLs by hash.
    - BatchLinkFetcher: retrieves existing links from cache and DB.
    - BatchLinkCreator: generates new links with collision resolution.
    - BatchResponseBuilder: constructs per-item response DTOs.

    All steps are performed within a single unit of work to ensure consistency.

    Guests get the same treatment here as on the single-link path: the same
    quota, the same default expiry, the same identifier recorded on what
    they create. Skipping all three turned this endpoint into a way around
    the limit -- a guest with nothing left of their daily ten could create
    a batch's worth of permanent links that counted as nobody's.

    Attributes:
        uow_factory: Callable factory for creating Unit of Work instances.
        cache: Link cache implementation.
        base_url: Base URL of the service for building short URLs.
        logger: Application logger.
        audit_logger: Audit logger for significant events.
        batch_limit: Maximum number of URLs accepted in one request.
        guest_link_limit: Max number of guest links per window.
        guest_link_window_days: Time window in days for guest link counting.
        default_guest_ttl_seconds: Default TTL for guest-created links.
        stats_cache: Cache of service-wide totals, dropped when links are
            created because the totals it holds have just gone stale.
        grouper: Validates and groups the input URLs.
        fetcher: Finds links that already exist.
        creator: Builds new links with unique codes.
        builder: Turns created links into per-item responses.
    """

    uow_factory: Callable[[], UnitOfWork]
    cache: LinkCache
    stats_cache: StatsCache
    base_url: str
    logger: Logger
    audit_logger: AuditLogger
    batch_limit: int
    guest_link_limit: int
    guest_link_window_days: int
    default_guest_ttl_seconds: int

    grouper: UrlGrouper
    fetcher: BatchLinkFetcher
    creator: BatchLinkCreator
    builder: BatchResponseBuilder

    def execute(self, urls: List[str], context: RequestContext) -> BatchCreateResponse:
        """
        Run the batch creation workflow.

        Args:
            urls: List of raw URL strings (max batch_limit).
            context: Request context.

        Returns:
            BatchCreateResponse with per-URL results and aggregates.

        Raises:
            ValueError: If batch size exceeds limit.
        """
        log = self._get_logger(self.logger, context)
        audit = self._get_audit_logger(self.audit_logger, context)
        start_time = time.perf_counter()

        if not urls:
            return BatchCreateResponse.empty()
        
        if len(urls) > self.batch_limit:
            log.warning(
                "Batch limit exceeded", requested=len(urls), limit=self.batch_limit
            )
            raise ValidationError(
                f"Batch limit exceeded. Max: {self.batch_limit}, requested: {len(urls)}",
                field="urls",
            )
        
        log.info("Starting batch link creation", count=len(urls))

        # 1. Group URLs by hash, separating valid/invalid
        groups = self.grouper.group(urls)
        valid_groups = [g for g in groups.values() if g["is_valid"]]
        invalid_groups = [g for g in groups.values() if not g["is_valid"]]

        # Build responses for invalid URLs immediately
        invalid_results = []
        for g in invalid_groups:
            for url in g["urls"]:
                invalid_results.append(
                    BatchItemResponse.error_(url=url, error=g["error"])
                )
        
        if not valid_groups:
            return BatchCreateResponse.from_results(invalid_results)
        
        # Extract owner from context
        owner_id = OwnerID(context.current_user.id) if context.current_user else None

        # Guests: scope, default expiry and what is left of the quota. A
        # guest is an unauthenticated caller we can name; a context with no
        # address is a call from outside a request (the CLI), which neither
        # the quota nor the guest expiry is meant for.
        guest_id = context.remote_addr if owner_id is None else None
        ttl_seconds = self.default_guest_ttl_seconds if guest_id is not None else 0

        scope = (
            DedupScope.for_owner(owner_id.value)
            if owner_id
            else DedupScope.for_guest(guest_id)
        )

        # 2. Look up and create, retrying the whole transaction if another
        # request claimed one of our codes first. Freedom of a code is
        # settled by the unique index, not by the lookup before the insert;
        # on the retry the winner's rows are visible, so the resolver picks
        # around them instead of failing the batch.
        for attempt in range(self.creator.max_attempts):
            try:
                (
                    fetched_results, groups_to_create, links_to_cache,
                    quota_results, saved_links,
                ) = self._look_up_and_create(
                    valid_groups, scope, owner_id, guest_id, ttl_seconds,
                    log, audit,
                )
                break
            except LinkConflictError:
                log.info(
                    "Lost a race for a short code, retrying the batch",
                    attempt=attempt + 1,
                )
        else:
            raise LinkConflictError(
                "Batch creation kept losing races with concurrent creations"
            )

        # 3. Nothing is written to the cache here, for the reason spelled
        # out in GetLinkInfoUseCase: the write lands after the transaction
        # above has closed, and a DELETE committed in between has already
        # done its invalidating -- so a batch of a hundred links writes the
        # deleted one straight back, and the redirect serves a link every
        # API surface reports as gone for as long as CACHE_LINK_TTL, an hour
        # in production. Reproduced against real PostgreSQL and Redis in
        # three rounds out of twelve, with the DELETE fired 50 ms into the
        # batch. Nothing in the service could then clear it: a second
        # DELETE answers 404 without invalidating, and the sweep never sees
        # a row that is not there.
        #
        # The path loses nothing by not warming: the redirect warms both
        # levels from its own repository hit the first time a code is used,
        # and most of a batch is never opened at all.
        log.debug("Links created", count=len(links_to_cache + saved_links))

        # 4. The totals the statistics cache holds are now wrong -- by as
        # much as a whole batch. The single-creation path, the delete path
        # and the expiry sweep all drop this key; this one did not, and
        # /api/v1/stats then under-reported for the rest of CACHE_STATS_TTL.
        if saved_links:
            self.stats_cache.delete_stats()

        # 5. A batch in which the quota refused every single item is the
        # same refusal the single-link path answers 429 to, and it used to
        # come back 200 here -- the same condition, two statuses, depending
        # on which endpoint was asked. A batch that got anything at all
        # done, including reporting a malformed URL, keeps its 200 and its
        # per-item errors: that is what the response format is for.
        if quota_results and not (saved_links or fetched_results or invalid_results):
            raise GuestLinkLimitExceededError(
                f"Guest link limit of {self.guest_link_limit} exceeded.",
                retry_after_seconds=self.guest_link_window_days * 24 * 3600,
            )

        # 6. Build DTOs for newly created links
        new_results = self.builder.build_from_new_links(
            groups_to_create, saved_links, self.base_url
        )

        # 5. Combine all results
        all_results = (
            fetched_results + new_results + quota_results + invalid_results
        )
        response = BatchCreateResponse.from_results(all_results)

        processing_time = time.perf_counter() - start_time
        log.info(
            "Batch link creation completed",
            total=response.total,
            successful=response.successful,
            failed=response.failed,
            cache_hits=response.from_cache_count,
            db_hits=response.from_db_count,
            new=response.new_count,
            time_sec=round(processing_time, 3),
        )
        return response

    def _look_up_and_create(
        self, valid_groups, scope, owner_id, guest_id, ttl_seconds, log, audit
    ):
        """
        Run one attempt at the lookup-and-create transaction.

        Args:
            valid_groups: Grouped, validated URLs.
            scope: The scope to deduplicate within.
            owner_id: Owner of new links, or ``None`` for guests.
            guest_id: Identifier a guest's links are counted under.
            ttl_seconds: Time-to-live for new links.
            log: Bound logger.
            audit: Bound audit logger.

        Returns:
            Tuple of fetched results, the groups that were created, links to
            cache, per-item quota errors, and the saved links.

        Raises:
            LinkConflictError: If storing lost a race with another request.
        """
        with self.uow_factory() as uow:
            repo = uow.links
            fetched_results, groups_to_create, links_to_cache = self.fetcher.fetch(
                repository=repo,
                groups=valid_groups,
                base_url=self.base_url,
                scope=scope,
            )

            # Counted here rather than up front, in the transaction that
            # goes on to insert. It does not make the count atomic -- see
            # the note on `_apply_guest_quota` -- but a count taken in a
            # unit of work that has already closed leaves a window as wide
            # as the whole lookup.
            remaining_quota = None
            if guest_id is not None:
                # Serialised against this guest's other requests, so the
                # allowance is read and spent as one decision. Without it a
                # batch is worth a whole quota to every concurrent caller.
                repo.lock_guest_quota(guest_id)
                used = repo.count_guest_links_by_identifier(
                    guest_id, self.guest_link_window_days
                )
                remaining_quota = max(0, self.guest_link_limit - used)

            # Only links that have to be created draw on the quota; being
            # handed one that already exists costs nothing.
            groups_to_create, quota_results = self._apply_guest_quota(
                groups_to_create, remaining_quota, log
            )

            # Create new links for the missing groups
            new_links = self.creator.create_new_links(
                repository=repo,
                groups=groups_to_create,
                owner_id=owner_id,
                guest_identifier=guest_id,
                ttl_seconds=ttl_seconds,
            )

            # Persist them
            saved_links = []
            if new_links:
                saved_links = repo.save_many(new_links)
                log.debug("New links saved", count=len(saved_links))

            uow.commit()

            # Audited after the commit, as the single-link path does. The
            # transaction above is retried whole when it loses a race for a
            # short code, so writing the audit line inside it recorded
            # creations that were then rolled back -- and the audit trail is
            # the record of what happened, not of what was attempted.
            if saved_links:
                batch_id = str(uuid.uuid4())
                for link in saved_links:
                    audit.log_url_created(
                        short_code=link.short_code.value,
                        original_url=link.original_url.value,
                        batch_id=batch_id
                    )

        return (
            fetched_results, groups_to_create, links_to_cache,
            quota_results, saved_links,
        )

    def _apply_guest_quota(
        self, groups_to_create: List[dict], remaining: Optional[int], log: Logger
    ) -> Tuple[List[dict], List[BatchItemResponse]]:
        """
        Trim the groups to what the caller's quota still allows.

        The batch is not refused as a whole: the response format already
        carries a result per URL, so what fits is created and what does not
        comes back as a per-item error. That keeps a guest with two slots
        left from losing a batch of ten entirely.

        Concurrency is handled a level down: the transaction takes an
        advisory lock on the guest identifier before reading the allowance,
        so this arithmetic is never done against a number another request is
        about to spend. On engines without such a lock -- SQLite, i.e. local
        development and the test suite -- the limit is advisory.

        Args:
            groups_to_create: Groups that need a new link, in input order.
            remaining: Links the caller may still create, or ``None`` when
                no quota applies.
            log: Bound logger.

        Returns:
            Tuple of the groups to create and the per-item errors for the
            rest.
        """
        if remaining is None or len(groups_to_create) <= remaining:
            return groups_to_create, []

        allowed = groups_to_create[:remaining]
        refused = groups_to_create[remaining:]

        log.warning(
            "Guest link limit reached mid-batch",
            limit=self.guest_link_limit,
            created=len(allowed),
            refused=len(refused),
        )

        error = f"Guest link limit of {self.guest_link_limit} exceeded."
        quota_results = [
            BatchItemResponse.error_(url=url, error=error)
            for group in refused
            for url in group["urls"]
        ]
        return allowed, quota_results
