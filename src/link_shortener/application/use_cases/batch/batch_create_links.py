from dataclasses import dataclass

import time
from typing import List, Optional, Tuple
import uuid

from link_shortener.application.dtos.batch import BatchCreateResponse, BatchItemResponse
from link_shortener.application.dtos.refusal import Refusal
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.context import RequestContext

from link_shortener.application.ports.cache.link_service_stats_cache import (
    StatsCache,
)
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.application.use_cases.batch.creator import BatchLinkCreator
from link_shortener.application.use_cases.batch.fetcher import BatchLinkFetcher
from link_shortener.application.use_cases.batch.grouper import UrlGrouper
from link_shortener.application.use_cases.batch.groups import UrlGroup
from link_shortener.application.use_cases.batch.response_builder import BatchResponseBuilder
from link_shortener.domain.exceptions import (
    LinkConflictError, ValidationError
)
from link_shortener.domain.policies.guest_quota_policy import (
    guest_allowance, guest_quota_spent,
)
from link_shortener.domain.value_objects.dedup_scope import DedupScope
from link_shortener.domain.value_objects.owner_id import OwnerID
from link_shortener.domain.entities.link import Link
from link_shortener.domain.i18n import N_


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
        base_url: Base URL of the service for building short URLs.
        logger: Application logger.
        audit_logger: Audit logger for significant events.
        batch_limit: Maximum number of URLs accepted in one request.
        guest_link_limit: Max number of guest links per window.
        guest_link_window_days: Time window in days for guest link counting.
        default_guest_ttl_seconds: Default TTL for guest-created links.
        max_collision_attempts: How many times the whole transaction is
            retried when it loses a race for a short code. Its own, as on
            the single-link path: it used to be read off ``creator``,
            whose number answers a different question -- how many salted
            codes one hash is offered before it is given up on. One value
            fed both, so the two could never be tuned apart, and the
            reader of either had to know the other existed.
        stats_cache: Cache of service-wide totals, dropped when links are
            created because the totals it holds have just gone stale.
        grouper: Validates and groups the input URLs.
        fetcher: Finds links that already exist.
        creator: Builds new links with unique codes.
        builder: Turns created links into per-item responses.
    """

    uow_factory: UnitOfWorkFactory
    stats_cache: StatsCache
    base_url: str
    logger: Logger
    audit_logger: AuditLogger
    batch_limit: int
    guest_link_limit: int
    guest_link_window_days: int
    default_guest_ttl_seconds: int
    max_collision_attempts: int

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
            ValidationError: If the batch carries more URLs than the limit.
                Not ``ValueError``, which is what this said and what a
                caller writing ``except ValueError`` would have caught
                nothing with: ``DomainError`` descends from ``Exception``,
                and ``create_short_link`` has a comment of its own about
                the two not being the same thing.
            GuestLinkLimitExceededError: If the guest's allowance refused
                every item and nothing else in the batch got done.
            LinkConflictError: If every attempt lost a race for a code.
        """
        log = self._get_logger(self.logger, context)
        audit = self._get_audit_logger(self.audit_logger, context)
        start_time = time.perf_counter()

        # Every exit reports the duration, not only the one at the end.
        # Filled in on the last return alone, the field went on being 0.0
        # for a batch of nothing and for a batch that was all malformed --
        # the two answers a caller is most likely to be timing.
        if not urls:
            return BatchCreateResponse.from_results(
                [], processing_time_seconds=time.perf_counter() - start_time
            )

        if len(urls) > self.batch_limit:
            log.warning(
                "Batch limit exceeded", requested=len(urls), limit=self.batch_limit
            )
            raise ValidationError(
                      f"Batch limit exceeded. Max: {self.batch_limit}, "
                      f"requested: {len(urls)}",
                      field="urls",
                      template=N_(
                          "Batch limit exceeded. Max: %(max)s, requested: %(requested)s"
                      ),
                      params={"max": self.batch_limit, "requested": len(urls)},
                  )

        log.info("Starting batch link creation", count=len(urls))

        # 1. Group URLs by hash, and take the refused ones aside
        valid_groups, rejected = self.grouper.group(urls)

        # Build responses for invalid URLs immediately
        invalid_results = [
            BatchItemResponse.error_(url=item.url, error=item.refusal)
            for item in rejected
        ]

        if not valid_groups:
            return BatchCreateResponse.from_results(
                invalid_results,
                processing_time_seconds=time.perf_counter() - start_time,
            )

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
        for attempt in range(self.max_collision_attempts):
            try:
                (
                    fetched_results, groups_to_create, links_found_in_db,
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
        log.debug(
            "Batch lookup and creation done",
            found=len(links_found_in_db),
            created=len(saved_links),
        )

        # 4. The totals the statistics cache holds are now wrong -- by as
        # much as a whole batch. The single-creation path, the delete path
        # and the expiry sweep all drop this key; this one did not, and
        # /api/v1/stats then under-reported for the rest of CACHE_STATS_TTL.
        if saved_links:
            self.stats_cache.delete_stats()

        # 5. A batch in which the quota refused every single item is the
        # same refusal the single-link path answers 429 to, so it answers
        # 429 here as well rather than 200. A batch that got anything at
        # all done, including reporting a malformed URL, keeps its 200 and
        # its per-item errors: that is what the response format is for.
        if quota_results and not (saved_links or fetched_results or invalid_results):
            raise guest_quota_spent(
                self.guest_link_limit, self.guest_link_window_days
            )

        # 6. Build DTOs for newly created links
        new_results = self.builder.build_from_new_links(
            groups_to_create, saved_links, self.base_url
        )

        # 7. Combine all results
        all_results = (
            fetched_results + new_results + quota_results + invalid_results
        )
        processing_time = time.perf_counter() - start_time
        response = BatchCreateResponse.from_results(
            all_results, processing_time_seconds=processing_time
        )

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
        self,
        valid_groups: List[UrlGroup],
        scope: DedupScope,
        owner_id: Optional[OwnerID],
        guest_id: Optional[str],
        ttl_seconds: int,
        log: Logger,
        audit: AuditLogger,
    ) -> Tuple[
        List[BatchItemResponse], List[UrlGroup], List[Link],
        List[BatchItemResponse], List[Link],
    ]:
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
            fetched_results, groups_to_create, links_found_in_db = self.fetcher.fetch(
                repository=repo,
                groups=valid_groups,
                base_url=self.base_url,
                scope=scope,
            )

            # Read inside the transaction that goes on to insert, and read
            # under a lock; both reasons are on ``guest_allowance``, which
            # is also where the single-link path reads it.
            remaining_quota = None
            if guest_id is not None:
                remaining_quota = guest_allowance(
                    repo, guest_id, self.guest_link_limit,
                    self.guest_link_window_days,
                )

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
            fetched_results, groups_to_create, links_found_in_db,
            quota_results, saved_links,
        )

    def _apply_guest_quota(
        self, groups_to_create: List[UrlGroup], remaining: Optional[int],
        log: Logger,
    ) -> Tuple[List[UrlGroup], List[BatchItemResponse]]:
        """
        Trim the groups to what the caller's quota still allows.

        The batch is not refused as a whole: the response format already
        carries a result per URL, so what fits is created and what does not
        comes back as a per-item error. That keeps a guest with two slots
        left from losing a batch of ten entirely.

        Concurrency is handled where the allowance is read:
        ``guest_allowance`` locks the guest identifier before counting, so
        this arithmetic is never done against a number another request is
        about to spend. What that lock is worth, and what it is worth on an
        engine that has none, is written there.

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

        # The same refusal the whole-batch branch raises, and the same
        # sentence: written as a finished f-string here, it was the one
        # answer in this response nobody could translate.
        refusal = Refusal.from_error(
            guest_quota_spent(self.guest_link_limit, self.guest_link_window_days)
        )
        quota_results = [
            BatchItemResponse.error_(url=url, error=refusal)
            for group in refused
            for url in group.urls
        ]
        return allowed, quota_results
