from dataclasses import dataclass

import time
from typing import List
import uuid

from link_shortener.domain import LinkRepository
from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.responses import BatchCreateResponse, BatchItemResponse
from link_shortener.application.ports.cache.link_cache import LinkCache
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.application.use_cases.batch.creator import BatchLinkCreator
from link_shortener.application.use_cases.batch.fetcher import BatchLinkFetcher
from link_shortener.application.use_cases.batch.grouper import UrlGrouper
from link_shortener.application.use_cases.batch.response_builder import BatchResponseBuilder


@dataclass
class BatchCreateLinksUseCase(BaseUseCase):
    """
    Use case for batch creation of short links.

    Coordinates the work of helper components:
        - UrlGrouper: groups URLs by their hash, validates schemes.
        - BatchLinkFetcher: retrieves existing links from cache and database.
        - BatchLinkCreator: creates new Link entities handling code collisions.
        - BatchResponseBuilder: builds DTOs for newly created links.

    Attributes:
        repository: Link repository for database operations.
        cache: Cache for storing Link objects.
        base_url: Base URL of the service (used to build short URLs).
        logger: Application logger.
        audit_logger: Audit logger for significant events.
        batch_limit: Maximum number of URLs allowed in a single batch request.
        grouper: Component that groups URLs by hash.
        fetcher: Component that fetches existing links.
        creator: Component that creates new links.
        builder: Component that builds response items for new links.
    """

    repository: LinkRepository
    cache: LinkCache
    base_url: str
    logger: Logger
    audit_logger: AuditLogger
    batch_limit: int = 100

    grouper: UrlGrouper
    fetcher: BatchLinkFetcher
    creator: BatchLinkCreator
    builder: BatchResponseBuilder
    
    def execute(self, urls: List[str], context: RequestContext) -> BatchCreateResponse:
        """
        Execute batch link creation.

        Steps:
            1. Validate batch size.
            2. Group URLs by hash (using injected grouper).
            3. Fetch existing links from cache and database (using injected fetcher).
            4. Create new links for missing URLs (using injected creator).
            5. Save new links to repository.
            6. Cache all links (existing and new).
            7. Build and aggregate responses (using injected builder).

        Args:
            urls: List of URLs to shorten.
            context: Request context with metadata (IP, user agent, etc.).

        Returns:
            BatchCreateResponse containing results for each URL and aggregated statistics.

        Raises:
            ValueError: If the number of URLs exceeds batch_limit
        """
        log = self._get_logger(self.logger, context)
        start_time = time.perf_counter()

        if not urls:
            return BatchCreateResponse.empty()
        
        if len(urls) > self.batch_limit:
            log.warning(
                "Batch limit exceeded", requested=len(urls), limit=self.batch_limit
            )
            raise ValueError(
                f"Batch limit exceeded. Max: {self.batch_limit}, requested: {len(urls)}"
            )
        
        log.info("Starting batch link creation", count=len(urls))

        # 1. Group URLs
        groups = self.grouper.group(urls)

        # Separate valid and invalid
        valid_groups = [g for g in groups.values() if g["is_valid"]]
        invalid_groups = [g for g in groups.values() if not g["is_valid"]]

        # Build responses for invalid URLs
        invalid_results = []
        for g in invalid_groups:
            for url in g["urls"]:
                invalid_results.append(
                    BatchItemResponse.error_(url=url, error=g["error"])
                )
        
        if not valid_groups:
            return BatchCreateResponse.from_results(invalid_results)
        
        # 2. Fetch from cache and DB
        fetched_results, groups_to_create, links_to_cache = self.fetcher.fetch(
            valid_groups, self.base_url
        )

        # 3. Create new links for missing groups
        new_links = self.creator.create_new_links(groups_to_create)

        # 4. Save new links to repository
        saved_links = []
        if new_links:
            saved_links = self.repository.save_many(new_links)
            batch_id = str(uuid.uuid4())
            for link in saved_links:
                self.audit_logger.log_url_created(link, context, batch_id=batch_id)
            log.debug("New links saved", count=len(saved_links))
        

        # 5. Cache all links (from DB and newly created)
        all_to_cache = links_to_cache + saved_links
        if all_to_cache:
            self.cache.save_many(all_to_cache)
            log.debug("Links cached", count=len(all_to_cache))
        
        # 6. Build responses for new links
        new_results = self.builder.build_from_new_links(
            groups_to_create, saved_links, self.base_url
        )

        # 7. Combine all results
        all_results = fetched_results + new_results + invalid_results
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