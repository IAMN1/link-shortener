from dataclasses import dataclass

import time
from typing import Callable, List
import uuid

from link_shortener.application.dtos.batch import BatchCreateResponse, BatchItemResponse
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.context import RequestContext

from link_shortener.application.ports.cache.link_cache import LinkCache
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.application.use_cases.batch.creator import BatchLinkCreator
from link_shortener.application.use_cases.batch.fetcher import BatchLinkFetcher
from link_shortener.application.use_cases.batch.grouper import UrlGrouper
from link_shortener.application.use_cases.batch.response_builder import BatchResponseBuilder
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
    """

    uow_factory: Callable[[], UnitOfWork]
    cache: LinkCache
    base_url: str
    logger: Logger
    audit_logger: AuditLogger
    batch_limit: int

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
            raise ValueError(
                f"Batch limit exceeded. Max: {self.batch_limit}, requested: {len(urls)}"
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
        user = context.current_user.id if context.current_user else None
        owner_id = OwnerID(user)

        # 2. Fetch existing links from cache and DB, groups missing
        with self.uow_factory() as uow:
            repo = uow.links
            fetched_results, groups_to_create, links_to_cache = self.fetcher.fetch(repository=repo, groups=valid_groups, base_url=self.base_url)

            # 3. Create new links for missing groups
            new_links = self.creator.create_new_links(repository=repo, groups=groups_to_create, owner_id=owner_id)

            # 4. Persist new links
            saved_links = []
            if new_links:

                saved_links = repo.save_many(new_links)
                batch_id = str(uuid.uuid4())
                for link in saved_links:
                    audit.log_url_created(
                        short_code=link.short_code.value,
                        original_url=link.original_url.value,
                        batch_id=batch_id
                    )
                log.debug("New links saved", count=len(saved_links))

            uow.commit()
        

        # 5. Update cache with all links (existing DB hits + new)
        all_to_cache = links_to_cache + saved_links
        if all_to_cache:
            self.cache.save_many(all_to_cache)
            log.debug("Links cached", count=len(all_to_cache))
        
        # 6. Build DTOs for newly created links
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
