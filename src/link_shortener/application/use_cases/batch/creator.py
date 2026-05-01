from collections import defaultdict, deque
from typing import Dict, List, Optional

from link_shortener.domain import (
    Link, CodeGenerator, LinkRepository, ShortCode, UrlHash
)
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.domain.value_objects.owner_id import OwnerID


class BatchLinkCreator:
    """
    Creates new ``Link`` entities for groups not found in cache or DB.

    Implements a batch collision resolution algorithm: generates initial
    codes, batch-checks existing codes, and resolves collisions with
    salted codes using a queue.
    """
    def __init__(self, code_generator: CodeGenerator, logger: Logger, max_attempts: int):
        """
        Args:
            code_generator: The domain code generation policy.
            logger: Application logger.
            max_attempts: Maximum collision resolution attempts per hash.
        """
        self.code_generator = code_generator
        self.logger = logger
        self.max_attempts = max_attempts
    
    def create_new_links(self, repository: LinkRepository, groups: List[Dict], owner_id: OwnerID = None) -> List[Link]:
        """
        Generate unique short codes and instantiate Link entities.

        Steps:
            1. Generate an initial code for each group.
            2. Batch-check which codes already exist in the repository.
            3. Resolve collisions by generating salted codes up to ``max_attempts``.
            4. Create a Link for each group with a unique code.

        Args:
            repository: Link repository (for existence checks).
            groups: List of group dicts with keys ``hash``, ``original_url``, ``urls``.
            owner_id: Optional OwnerID value object.

        Returns:
            List of new Link entities (not yet persisted).
        """
        if not groups:
            return []
        
        # 1. Generate initial codes
        hash_to_code = {}
        for group in groups:
            original_url = group["original_url"]
            code = self.code_generator.generate_for_url(original_url)
            hash_to_code[group["hash"]] = code
        
        # 2. Check collisions in one batch
        unique_codes = list(set(hash_to_code.values()))
        existing_map = repository.find_by_codes(unique_codes)

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
                    owner=owner_id
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

        Algorithm:
            - Maintain a set of occupied codes.
            - For each hash, if its code is free, accept it.
            - If the code belongs to a different URL, generate a salted code
              (increasing attempt counter). If the new code is still occupied,
              push the hash back onto the queue for another attempt.

        Args:
            hash_to_code: Mapping from URL hash to initially generated code.
            existing_map: Map from existing codes to their Links (None if free).
            groups: Original groups (needed for hash → group lookup).

        Returns:
            Dictionary mapping each URL hash to a unique short code.
        """
        resolved = {}
        attempts = defaultdict(int)
        queue = deque(hash_to_code.items())
        occupied = {code for code, link in existing_map.items() if link is not None}
        hash_to_group = {g["hash"]: g for g in groups}

        while queue:
            url_hash, code = queue.popleft()

            if code in occupied:
                existing = existing_map.get(code)

                # Collision with a different URL?
                if existing is not None and existing.url_hash != url_hash:
                    attempts[url_hash] += 1
                    if attempts[url_hash] > self.max_attempts:
                        self.logger.warning(
                            "Max collision attempts exceeded", hash=url_hash.value[:10]
                        )
                        continue

                    group = hash_to_group[url_hash]
                    new_code = self.code_generator.generate_unique(
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
