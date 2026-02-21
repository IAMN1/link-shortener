from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional
import uuid


from link_shortener.application import (
    BatchCreateResponse, BatchItemResponse, LinkCache, Logger, AuditLogger
)

from link_shortener.domain import (
    Link, LinkRepository, OriginalUrl, ShortCode, ShorteningPolicy, UrlHash
)


@dataclass
class BatchCreateLinksUseCase:
    """
    Use case: Batch creation of short links for multiple URLs.

    This use case processes a list of URLs, performing deduplication,
    cache lookups, database queries, and new link creation efficiently
    in batches. It handles:
    - Validation of each URL.
    - Grouping by URL hash to avoid duplicate processing.
    - Checking cache and database for existing links.
    - Resolving short code collisions with retries.
    - Saving new links in bulk.
    - Auditing and caching results.
    """

    repository: LinkRepository
    cache: LinkCache
    shortening_policy: ShorteningPolicy
    base_url: str
    logger: Logger
    audit_logger: AuditLogger
    batch_limit: int = 100

    def execute(
        self, urls: List[str], user_ip: Optional[str] = None, user_agent: Optional[str] = None
    ) -> BatchCreateResponse:
        """
        Execute the batch creation use case.

        Args:
            urls (List[str]): List of URLs to shorten.
            user_ip (Optional[str], optional): IP address of the user (for audit). 
                Defaults to None.
            user_agent (Optional[str], optional): User-Agent string (for audit). 
                Defaults to None.

        Raises:
            ValueError: If the number of URLs exceeds batch_limit.
            RuntimeError: If batch processing fails unexpectedly.

        Returns:
            BatchCreateResponse: BatchCreateResponse containing results 
                for each URL and aggregated stats.
        """
        if not urls:
            return BatchCreateResponse.empty()

        # 1. Enforce batch size limit
        if len(urls) > self.batch_limit:
            self.logger.warning(
                "Batch limit exceeded", url_requested=len(urls), limit=self.batch_limit
            )

            raise ValueError(
                f"Batch limit exceeded. Max: {self.batch_limit}, requested: {len(urls)}"
            )

        start_time = datetime.now()

        self.logger.info("Starting batch link creation", urls_count=len(urls))

        try:
            # 2. Group URLs by their hash (deduplication)
            url_groups = self._group_urls_by_hash(urls)

            self.logger.debug(
                "URLs grouped by hash",
                unique_hashes=len(url_groups),
                total_urls=len(urls),
            )

            # 3. Process all groups in batch-aware manner
            batch_results = self._process_groups_batch(url_groups, user_ip, user_agent)

            # 4. Build the final response
            response = BatchCreateResponse.from_results(batch_results)

            processing_time = (datetime.now() - start_time).total_seconds()

            self.logger.info(
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

        except Exception as e:
            self.logger.exception(
                "Batch link creation failed", url_count=len(urls), error=str(e)
            )
            raise RuntimeError(f"Batch processing failed: {str(e)}")

    def _group_urls_by_hash(self, urls: List[str]) -> Dict[str, Dict]:
        """
        Group URLs by their computed hash.

        Valid URLs are grouped under their hash key; invalid URLs are grouped
        under separate keys with an error flag.

        Returns:
            Dict[str, Dict]: Dictionary where key is hash (or error key)
            and value contains:
                - hash: UrlHash (if valid)
                - original_url: OriginalUrl (if valid)
                - urls: list of input strings for this group
                - is_valid: bool
                - error: error message (if invalid)
        """

        groups = {}
        invalid_counter = 0

        for url in urls:
            try:
                # Validate and create value objects
                original_url = OriginalUrl(url)

                # Вычисление хэша
                url_hash = self.shortening_policy.calculate_hash(original_url)
                hash_key = url_hash.value

                if hash_key not in groups:
                    groups[hash_key] = {
                        "hash": url_hash,
                        "original_url": original_url,
                        "urls": [],
                        "is_valid": True,
                    }
                groups[hash_key]["urls"].append(url)

            except ValueError as e:
                # Invalid URL – create a separate error group
                error_key = f"invalid_{invalid_counter}"
                invalid_counter += 1

                groups[error_key] = {
                    "hash": None,
                    "original_url": None,
                    "urls": [url],
                    "is_valid": False,
                    "error": str(e),
                }

                self.logger.warning("Invalid URL in batch", url=url[:50], error=str(e))

        return groups

    def _process_groups_batch(
        self, groups: Dict[str, Dict], user_ip: Optional[str] = None, user_agent: Optional[str] = None
    ) -> List[BatchItemResponse]:
        """
        Process all groups in batch-aware steps:

        1. Separate valid and invalid groups.
        2. Check cache for all valid groups.
        3. For cache misses, query repository.
        4. For groups not in DB, create new links.
        5. Build results for all cases.
        """

        results = []

        # 1. Split valid and invalid groups
        valid_groups = []
        invalid_results = []

        for _, group in groups.items():
            if not group.get("is_valid", True):
                # Обработка невалидных групп
                error_msg = group.get("error", "Invalid_url")
                for url in group["urls"]:
                    invalid_results.append(
                        BatchItemResponse.error_(url=url, error=error_msg)
                    )
            else:
                valid_groups.append(group)

        if not valid_groups:
            # No valid URLs to process
            return invalid_results

        # 2. Batch cache lookup for all valid groups
        url_hashes = [group["hash"] for group in valid_groups]
        cached_links_map = self.cache.get_by_hashes(url_hashes)

        # 3. Separate groups found in cache vs. those not found
        groups_not_in_cache = []
        cache_results = []

        for group in valid_groups:
            url_hash = group["hash"]
            cached_link = cached_links_map.get(url_hash)

            if cached_link:
                # найдено в кэше
                for url in group["urls"]:
                    cache_results.append(
                        BatchItemResponse.success_(
                            url=url,
                            short_code=str(cached_link.short_code.value),
                            original_url=str(cached_link.original_url.value),
                            base_url=self.base_url,
                            clicks=cached_link.clicks,
                            from_cache=True,
                        )
                    )
            else:
                groups_not_in_cache.append(group)

        # If all groups were in cache, return combined results
        if not groups_not_in_cache:

            results.extend(cache_results)
            results.extend(invalid_results)
            return results

        # 4. Batch database lookup for groups not in cache
        missing_hashes = [group["hash"] for group in groups_not_in_cache]
        db_link_map = self.repository.find_by_hashes(missing_hashes)

        # 5. Separate groups found in DB vs. those needing creation
        groups_to_create = []
        db_results = []
        links_to_cache_from_db = []

        for group in groups_not_in_cache:
            url_hash = group["hash"]
            db_link = db_link_map.get(url_hash)

            if db_link:
                # найдено в БД - добавляем в кэш
                links_to_cache_from_db.append(db_link)

                for url in group["urls"]:
                    db_results.append(
                        BatchItemResponse.success_(
                            url=url,
                            short_code=str(db_link.short_code.value),
                            original_url=str(db_link.original_url.value),
                            base_url=self.base_url,
                            clicks=db_link.clicks,
                            is_new=False,
                        )
                    )
            else:
                groups_to_create.append(group)

        # 6. Create new links for remaining groups
        new_links = self._create_new_links_batch(groups_to_create) if groups_to_create else []

        # 7. Save new links to repository
        saved_links = []
        if new_links:
            saved_links = self.repository.save_many(new_links)

            # Audit each new link (optional: associate with batch_id)
            batch_id = str(uuid.uuid4())
            for link in saved_links:
                self.audit_logger.log_url_created(
                    link,
                    user_ip=user_ip,
                    user_agent=user_agent,
                    batch_id=batch_id
                )

        # 8. Cache all links (both from DB and newly created)
        links_to_cache = []
        links_to_cache.extend(links_to_cache_from_db)
        links_to_cache.extend(saved_links)

        if links_to_cache:
            self.cache.save_many(links_to_cache)

        # 9. Build results for newly created links
        new_results = self._create_new_link_results(groups_to_create, saved_links)

        # 10. Combine all results
        results.extend(cache_results)
        results.extend(db_results)
        results.extend(new_results)
        results.extend(invalid_results)
        return results

    def _create_new_links_batch(self, groups: List[Dict]) -> List[Link]:
        """
        Create new Link entities for groups that are not in cache or DB.

        This method handles short code collisions by generating alternative codes
        with increasing attempt numbers.

        Steps:
        - Generate a short code for each group (using the policy).
        - Check for code collisions with existing links in a single batch query.
        - Resolve collisions by generating salted codes.
        - Create domain Link objects.
        """

        # 1. Generate initial codes for all groups
        hash_to_code = {}

        for group in groups:
            original_url = group["original_url"]
            short_code = self.shortening_policy.generate_code_for_url(original_url)
            hash_to_code[group["hash"]] = short_code

        # 2. Check all generated codes for collisions in one batch
        unique_codes = list(set(hash_to_code.values()))
        existing_codes_map = self.repository.find_by_codes(unique_codes)

        # 3. Resolve collisions (may require multiple attempts)
        resolved_codes = self._resolve_collisions_batch(
            hash_to_code, existing_codes_map, groups
        )

        # 4. Create Link entities for groups with successfully resolved codes
        new_links = []
        for group in groups:
            url_hash = group["hash"]
            short_code = resolved_codes.get(url_hash)

            if not short_code:
                # Failed to resolve after max attempts – skip (should be rare)
                continue

            new_link = Link.create(
                url_hash=url_hash,
                short_code=short_code,
                original_url=group["original_url"],
            )
            new_links.append(new_link)

        return new_links

    def _resolve_collisions_batch(
        self,
        hash_to_code: Dict[UrlHash, ShortCode],
        existing_codes_map: Dict[ShortCode, Optional[Link]],
        groups: List[Dict],
    ) -> Dict[UrlHash, ShortCode]:
        """
        Resolve short code collisions in batch.

        For each hash-code pair, if the code already exists 
            and belongs to a different URL,
            generate a new code with a salted input (attempt count). 
        Keep trying up to max_attempts.

        Returns a dictionary mapping each URL hash to a unique short code.
        """

        resolved = {}
        collision_attempts = defaultdict(int)
        max_attempts = 5

        # Словарь для быстрого поиска группы по хэшу
        hash_to_group = {group["hash"]: group for group in groups}
        
        # Initialize queue with all (hash, initial_code) pairs
        processing_queue = deque(hash_to_code.items())
        
        # Set of already occupied codes 
        # (from DB and those we assign during resolution)
        occupied_codes = set(existing_codes_map.keys())

        while processing_queue:
            url_hash, short_code = processing_queue.popleft()

            if short_code in occupied_codes:

                # Code already exists; check if it belongs to the same URL
                existing_link = existing_codes_map.get(short_code)
                if existing_link and existing_link.url_hash != url_hash:

                    # Collision with a different URL – need to retry
                    attempt_key = (url_hash, short_code)
                    collision_attempts[attempt_key] += 1

                    if collision_attempts[attempt_key] > max_attempts:
                        continue  # Exceeded max attempts – skip this group

                    # Generate a new code with salt (attempt number)
                    group = hash_to_group[url_hash]
                    original_url = group["original_url"]
                    attempt = collision_attempts[attempt_key]

                    new_code = self.shortening_policy.generate_unique_code(
                        original_url, attempt
                    )

                    # Check if new code is free
                    if new_code not in occupied_codes:

                        # В случае, если новый код не вызывает коллизию
                        resolved[url_hash] = new_code
                        occupied_codes.add(new_code)

                    else:
                        # Still collides – push back to queue for another attempt
                        processing_queue.append((url_hash, new_code))
                else:
                    # code exists but it's the same URL -> treat as resolved
                    resolved[url_hash] = short_code
                    occupied_codes.add(short_code)
            else:
                # Code is unique – accept it
                resolved[url_hash] = short_code
                occupied_codes.add(short_code)

        return resolved

    def _create_new_link_results(
        self, groups: List[Dict], saved_links: List[Link]
    ) -> List[BatchItemResponse]:
        """
        Create BatchItemResponse objects for newly created links.

        For each group, the first URL is considered the "original" that
            triggered creation;
        subsequent URLs in the same group are duplicates and get 
            duplicate_of field set.
        """
        results = []

        # Словарь для быстрого поиска ссылки по хэшу
        hash_to_link = {link.url_hash: link for link in saved_links}

        for group in groups:
            url_hash = group["hash"]
            saved_link = hash_to_link.get(url_hash)

            if not saved_link:
                # Should not happen if creation succeeded, but handle gracefully
                for url in group["urls"]:
                    results.append(
                        BatchItemResponse.error_(url=url, error="Failed to save link")
                    )
                continue

            # First URL in the group -> new link
            results.append(
                BatchItemResponse.success_(
                    url=str(saved_link.original_url.value),
                    short_code=str(saved_link.short_code.value),
                    original_url=str(saved_link.original_url.value),
                    base_url=self.base_url,
                    clicks=saved_link.clicks,
                    is_new=True,
                )
            )

            # Remaining URLs in the group -> duplicates of the first
            for url in group["urls"][1:]:
                results.append(
                    BatchItemResponse.success_(
                        url=url,
                        short_code=str(saved_link.short_code.value),
                        original_url=str(saved_link.original_url.value),
                        base_url=self.base_url,
                        clicks=saved_link.clicks,
                        is_new=False,
                        duplicate_of=str(saved_link.original_url.value),
                    )
                )
        return results
