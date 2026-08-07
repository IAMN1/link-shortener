from collections import defaultdict
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
    
    def create_new_links(
        self,
        repository: LinkRepository,
        groups: List[Dict],
        owner_id: Optional[OwnerID] = None,
        guest_identifier: Optional[str] = None,
        ttl_seconds: int = 0,
    ) -> List[Link]:
        """
        Generate unique short codes and instantiate Link entities.

        Steps:
            1. Generate an initial code for each group.
            2. Batch-check which codes already exist in the repository.
            3. Resolve collisions by generating salted codes up to ``max_attempts``.
            4. Create a Link for each group with a unique code.

        The guest identifier and TTL are passed through for the same reason
        the single-link path sets them: without them a guest's batch links
        were permanent and were not counted as guest links at all, so the
        batch endpoint handed out unlimited immortal links to callers whose
        daily quota was already spent.

        Args:
            repository: Link repository (for existence checks).
            groups: List of group dicts with keys ``hash``, ``original_url``, ``urls``.
            owner_id: OwnerID of the creator, or ``None`` for guests.
            guest_identifier: Identifier a guest's links are counted under.
            ttl_seconds: Time-to-live for the new links; 0 means forever.

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

        # 2. Resolve collisions, asking the repository about every candidate
        resolved = self._resolve_collisions(hash_to_code, repository, groups)

        # 3. Create Link entities
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
                    owner=owner_id,
                    guest_identifier=guest_identifier,
                    ttl_seconds=ttl_seconds,
                )
            )
        return new_links
    
    def _resolve_collisions(
        self,
        hash_to_code: Dict[UrlHash, ShortCode],
        repository: LinkRepository,
        groups: List[Dict],
    ) -> Dict[UrlHash, ShortCode]:
        """
        Give every hash a code nobody holds.

        Works in rounds. Each round asks the repository about the whole set
        of current candidates in one query, takes the free ones, and
        generates replacements for the rest -- salted first, then random
        once the salted ladder is spent. Codes taken earlier in this batch
        count as occupied too, since the repository cannot know about them.

        **Every candidate is checked against the repository, not just the
        first one.** Asking once, up front, about the initial codes only --
        the previous shape of this method -- left the salted replacements
        checked against nothing but that first answer. A salted code that
        was in fact taken looked free, went into ``save_many``, and raised
        ``IntegrityError`` on ``urls.short_code``, which fails the *whole*
        batch with a 500. Two links for one URL in different scopes were
        enough to arrange it, and per-owner deduplication makes that an
        ordinary state.

        Args:
            hash_to_code: Mapping from URL hash to initially generated code.
            repository: Link repository, asked once per round.
            groups: Original groups (needed for hash → group lookup).

        Returns:
            Dictionary mapping each URL hash to a unique short code.
        """
        resolved = {}
        attempts = defaultdict(int)
        occupied = set()
        hash_to_group = {g["hash"]: g for g in groups}
        candidates = dict(hash_to_code)

        while candidates:
            stored = repository.find_by_codes(list(set(candidates.values())))
            occupied.update(
                code for code, link in stored.items() if link is not None
            )

            next_round = {}
            for url_hash, code in candidates.items():
                if code not in occupied:
                    resolved[url_hash] = code
                    # Claimed for this batch: the repository will not know
                    # about it until the transaction commits.
                    occupied.add(code)
                    continue

                attempts[url_hash] += 1
                if attempts[url_hash] > self.max_attempts * 2:
                    self.logger.warning(
                        "Max collision attempts exceeded",
                        hash=url_hash.value[:10],
                    )
                    continue

                group = hash_to_group[url_hash]
                if attempts[url_hash] <= self.max_attempts:
                    next_round[url_hash] = self.code_generator.generate_unique(
                        group["original_url"], attempts[url_hash]
                    )
                else:
                    # The salted ladder is a pure function of the URL, so it
                    # runs out after ``max_attempts`` and never yields
                    # anything new. Giving up there dropped an item from a
                    # batch that could perfectly well have been created.
                    next_round[url_hash] = self.code_generator.generate_fresh(
                        group["original_url"]
                    )

            candidates = next_round

        return resolved
