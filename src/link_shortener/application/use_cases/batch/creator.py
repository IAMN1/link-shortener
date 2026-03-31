from collections import defaultdict, deque
from typing import Dict, List, Optional

from link_shortener.domain import (
    Link, ShorteningPolicy, LinkRepository, ShortCode, UrlHash
)
from link_shortener.application.ports.logger.logger import Logger


class BatchLinkCreator:
    """
    Creates new Link entities for groups not found in cache or database.

    Handles short code collisions by generating alternative codes with increasing
    attempt numbers. Uses a batch collision resolution algorithm to minimize
    database round trips.
    """
    def __init__(self, repository: LinkRepository, policy: ShorteningPolicy, logger: Logger, max_attempts: int):
        """
        Initialize the creator.

        Args:
            repository: Link repository for checking code uniqueness.
            policy: Shortening policy for code generation.
            logger: Logger for recording warnings and errors.
            max_attempts: Maximum number of attempts to resolve a collision.
        """
        self.repository = repository
        self.policy = policy
        self.logger = logger
        self.max_attempts = max_attempts
    
    def create_new_links(self, groups: List[Dict]) -> List[Link]:
        """
        Create new Link entities for the given groups.

        Steps:
            1. Generate initial short codes for all groups.
            2. Batch check existing codes in the repository.
            3. Resolve collisions by generating salted codes.
            4. Create Link objects for groups with resolved codes.

        Args:
            groups: List of group dictionaries, each containing:
                - 'hash': UrlHash of the URL.
                - 'original_url': OriginalUrl value object.
                - 'urls': list of input URLs (first is canonical).

        Returns:
            List of new Link entities (not yet saved to repository)
        """
        if not groups:
            return []
        
        # 1. Generate initial codes
        hash_to_code = {}
        for group in groups:
            original_url = group["original_url"]
            code = self.policy.generate_code_for_url(original_url)
            hash_to_code[group["hash"]] = code
        
        # 2. Check collisions in one batch
        uniqie_codes = list(set(hash_to_code.values()))
        existing_map = self.repository.find_by_codes(uniqie_codes)

        # 3. Resolve collisions
        resolved = self._resolve_collisions(hash_to_code, existing_map, groups)

        # 4. Create Link entities
        new_links = []
        for group in groups:
            url_hash = group["hash"]
            code = resolved.get(url_hash)
            if not code:
                self.logger.error(
                    "Failed to resolve collision for hash", hash=url_hash.value[:10]
                )
                continue
            new_links.append(
                Link.create(
                    url_hash=url_hash,
                    short_code=code,
                    original_url=group["original_url"],
                )
            )
        return new_links
    
    def _resolve_collisions(
        self,
        hash_to_code: Dict[UrlHash, ShortCode],
        existing_map: Dict[ShortCode, Optional[Link]],
        groups: List[Dict],
    ) -> Dict[UrlHash, ShortCode]:
        """
        Resolve short code collisions using a queue and retries.

        This method processes all hash-code pairs, attempting to assign a unique
        code to each. If a code is already taken by a different URL, a new code
        is generated with a salt (attempt number). The process continues until
        either a unique code is found or max_attempts is exceeded.

        Args:
            hash_to_code: Mapping from URL hash to initially generated code.
            existing_map: Mapping from existing short codes to their Links
                          (only codes that already exist in the database).
            groups: List of groups (needed to retrieve original URL for salting).

        Returns:
            Dictionary mapping each URL hash to a unique short code.
        """
        resolved = {}
        attempts = defaultdict(int)
        queue = deque(hash_to_code.items())
        occupied = set(existing_map.keys())
        hash_to_group = {g["hash"]: g for g in groups}

        while queue:
            url_hash, code = queue.popleft()

            if code in occupied:
                existing = existing_map.get(code)

                # Collision with a different URL?
                if existing and existing.url_hash != url_hash:
                    attempts[url_hash] += 1
                    if attempts[url_hash] > self.max_attempts:
                        self.logger.warning(
                            "Max collision attempts exceeded", hash=url_hash.value[:10]
                        )
                        continue

                    group = hash_to_group[url_hash]
                    new_code = self.policy.generate_unique_code(
                        group["original_url"], attempts[url_hash]
                    )
                    if new_code not in occupied:
                        resolved[url_hash] = new_code
                        occupied.add(new_code)
                    else:
                        # Still colliding – push back to queue for another attempt
                        queue.append((url_hash, new_code))
                else:
                    # Code belongs to the same URL (should not happen in batch)
                    resolved[url_hash] = code
                    occupied.add(code)
            else:
                # Code is free – accept it
                resolved[url_hash] = code
                occupied.add(code)
        
        return resolved
