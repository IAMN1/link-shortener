from dataclasses import dataclass
import time
from typing import List, Optional


from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.link import ShortLinkResponse
from link_shortener.application.ports.cache.link_cache import LinkCache
from link_shortener.application.ports.cache.link_service_stats_cache import (
    StatsCache,
)
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import (
    UnitOfWork, UnitOfWorkFactory,
)
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import (
    DedupScope, Link, OriginalUrl, ShortCode, UrlHash,
    HashCalculator, CodeGenerator, OwnerID,
    ValidationError, CodeGenerationError, LinkCodeTakenError,
    LinkConflictError
)
from link_shortener.domain.policies.guest_quota_policy import (
    guest_allowance, guest_quota_spent,
)
from link_shortener.domain.policies.reserved_codes import is_reserved
from link_shortener.domain.i18n import N_


@dataclass
class CreateShortLinkUseCase(BaseUseCase):
    """
    Use case for creating a single short link.

    Orchestrates URL validation, deduplication, code generation, persistence and caching.

    Deduplication answers one question: has *this caller* already got a live
    link for this URL. Both halves are load-bearing. Matching on the URL
    alone handed the caller somebody else's link, which they could neither
    list nor delete; ignoring expiry handed them a dead code and made the
    URL unshortenable for good, since nothing creates a replacement while
    the expired row is still there to be found.

    Attributes:
        uow_factory: Callable factory for creating Unit of Work instances.
        cache: Link cache implementation for fast lookups.
        stats_cache: Cache of service-wide totals, dropped when a link is
            created because the totals it holds have just gone stale.
        hash_calculator: Strategy for computing URL hashes.
        code_generator: Strategy for generating short codes.
        base_url: Base URL of the service for building short URLs.
        logger: Application logger.
        audit_logger: Audit logger for significant events.
        allowed_schemes: List of allowed URL schemes (e.g., ['http', 'https']).
        max_url_length: Longest URL admitted, from ``MAX_URL_LENGTH``.
        allow_internal_targets: Whether destinations inside the deployment's
            own network are admitted, from ``ALLOW_INTERNAL_TARGETS``.
        guest_link_limit: Max number of guest links per window.
        guest_link_window_days: Time window in days for guest link counting.
        default_guest_ttl_seconds: TTL for guest-created links -- both the
            one applied when none is asked for and the most a guest may ask
            for.
        max_ttl_seconds: Longest lifetime any caller may ask for.
        max_collision_attempts: Maximum tries to generate a unique code.
    """

    uow_factory: UnitOfWorkFactory
    cache: LinkCache
    stats_cache: StatsCache
    hash_calculator: HashCalculator
    code_generator: CodeGenerator
    base_url: str
    logger: Logger
    audit_logger: AuditLogger
    allowed_schemes: List[str]
    max_url_length: int
    allow_internal_targets: bool
    guest_link_limit: int
    guest_link_window_days: int
    default_guest_ttl_seconds: int
    max_ttl_seconds: int
    max_collision_attempts: int = 5

    def execute(
        self, url: str, context: RequestContext, ttl_seconds: int = 0,
        custom_code: Optional[str] = None,
    ) -> ShortLinkResponse:
        """
        Execute the create short link use case.

        Args:
            url: The original URL to shorten.
            context: Request context with client metadata.
            ttl_seconds: Time-to-live in seconds (0 = forever).
            custom_code: Code the caller chose, instead of a generated one.

        Returns:
            ShortLinkResponse DTO with link details.

        Raises:
            ValidationError: If the URL is invalid or scheme not allowed.
            GuestLinkLimitExceededError: If the guest link limit is exceeded.
            CodeGenerationError: If no code could be stored after max attempts.
        """

        # Bind request context to the logger.
        log = self._get_logger(self.logger, context)
        audit = self._get_audit_logger(self.audit_logger, context)

        start_time = time.perf_counter()
        # The URL itself is not written here. This line runs before any
        # validation, so what it would write is whatever the caller sent --
        # and a few lines below it that can be an address rejected for
        # holding credentials in front of the host, by which point the
        # password is already in application.log. OWASP's Logging Cheat Sheet lists
        # authentication passwords among the data that "should usually not
        # be recorded directly in the logs". The address does get logged,
        # once it has been checked: ``audit.log_url_created`` masks it.
        log.info("Starting short link creation", url_length=len(url))

        try:

            # ---- 0. Bound the lifetime asked for ------------------
            self._validate_ttl(ttl_seconds)
            chosen_code = self._read_custom_code(custom_code)

            # ---- 1. Validate URL via value object ----------------
            original_url = OriginalUrl(
                url,
                allowed_schemes=tuple(self.allowed_schemes),
                max_length=self.max_url_length,
                allow_internal_targets=self.allow_internal_targets,
            )

            # ---- 2. Compute hash for deduplication ---------------
            url_hash = self.hash_calculator.calculate(original_url)

            # ---- Guest TTL ---------------------------------------
            # A guest is an unauthenticated caller we can *name*. A context
            # carrying no address at all is not a visitor with an unusual
            # one -- it is a call from outside any request, i.e. the CLI --
            # and neither the guest quota nor the guest expiry is meant for
            # it. Web callers always have an address, empty string at worst,
            # so none of them fall through this way.
            guest_id = context.remote_addr if not context.current_user else None
            if guest_id is not None:
                # The guest lifetime is a ceiling and not merely a default.
                # Applied only when nothing was asked for, it was advice:
                # ``ttl_seconds=10**9`` bought a guest a link for thirty-one
                # years, which is the whole of what the guest expiry exists
                # to prevent.
                ttl_seconds = (
                    self.default_guest_ttl_seconds
                    if ttl_seconds == 0
                    else min(ttl_seconds, self.default_guest_ttl_seconds)
                )

            owner_id_vo = (
                OwnerID(context.current_user.id) if context.current_user else None
            )
            scope = (
                DedupScope.for_owner(owner_id_vo.value)
                if owner_id_vo
                else DedupScope.for_guest(guest_id)
            )

            # ---- 3. Look for a link, or create one -----------------
            # Retried as a whole, in a fresh unit of work each time. Whether
            # a code is free is decided by the unique index, not by the
            # lookup that precedes the insert: between the two, another
            # request can commit. On the retry the winner's row is visible,
            # so this request either returns it as the existing link or
            # generates a code around it.
            for attempt in range(self.max_collision_attempts):
                try:
                    return self._find_or_create(
                        original_url, url_hash, scope, owner_id_vo,
                        guest_id, ttl_seconds, log, audit, chosen_code,
                    )
                except LinkConflictError:
                    log.info(
                        "Lost a race for a short code, retrying",
                        attempt=attempt + 1,
                        hash=url_hash.value[:10],
                    )

            raise CodeGenerationError(
                "Failed to store a short link: every attempt lost a race "
                "with a concurrent creation"
            )
        # There is deliberately no ``except ValueError`` here. Wrapping
        # this body -- the cache read, the repository, the unit of work --
        # and answering 400 would report a failure of the service as the
        # caller's mistake and put the text of an internal exception in
        # the response body. ``JSONDecodeError`` and ``UnicodeDecodeError``
        # are ``ValueError`` subclasses, so a corrupted cache entry alone
        # would reach it.
        # Everything the caller can actually get wrong raises
        # ``ValidationError``, which is not a ``ValueError`` and is answered
        # 400 by the handler; ``OriginalUrl`` keeps a bare ``ValueError``
        # from ``urlparse`` inside as well.
        except Exception as e:
            log.error("Error creating short link", error=str(e))
            raise e
        finally:
            duration = time.perf_counter() - start_time
            log.debug("Execution time", duration_ms=round(duration * 1000, 2))

    @staticmethod
    def _read_custom_code(custom_code: Optional[str]) -> Optional[ShortCode]:
        """
        Read a code the caller chose, or return nothing.

        Args:
            custom_code: The requested code, or ``None``.

        Returns:
            The validated code, or ``None`` when none was asked for.

        Raises:
            ValidationError: If the code is malformed or is one the service
                answers to itself.
        """
        if not custom_code:
            return None

        code = ShortCode(custom_code)
        if is_reserved(code.value):
            # Not a hijack -- the router prefers its own static rule -- but
            # a link that never resolves, handed over as if it worked.
            raise ValidationError(
                      f"'{code.value}' is reserved by the service and cannot be "
                      f"used as a short code",
                      field="code",
                      template=N_(
                          "'%(code)s' is reserved by the service and cannot be used "
                          "as a short code"
                      ),
                      params={"code": code.value},
                  )
        return code

    def _validate_ttl(self, ttl_seconds: int) -> None:
        """
        Refuse a lifetime the service will not grant.

        Without an upper bound the number went straight into a
        ``timedelta``, and past 251 616 310 632 seconds the addition to
        ``datetime.now()`` raises ``OverflowError`` -- which is not a
        ``ValueError``, so nothing on the way out caught it and an
        unauthenticated caller got a 500 out of a one-line request body.

        Args:
            ttl_seconds: Lifetime asked for, 0 meaning forever.

        Raises:
            ValidationError: If the lifetime exceeds ``MAX_TTL_SECONDS``.
        """
        if ttl_seconds > self.max_ttl_seconds:
            raise ValidationError(
                      f"ttl_seconds must not exceed {self.max_ttl_seconds}",
                      field="ttl_seconds",
                      template=N_("ttl_seconds must not exceed %(max)s"),
                      params={"max": self.max_ttl_seconds},
                  )

    def _find_or_create(
        self,
        original_url: OriginalUrl,
        url_hash: UrlHash,
        scope: DedupScope,
        owner_id_vo: Optional[OwnerID],
        guest_id: Optional[str],
        ttl_seconds: int,
        log: Logger,
        audit: AuditLogger,
        chosen_code: Optional[ShortCode] = None,
    ) -> ShortLinkResponse:
        """
        Return the caller's live link for this URL, creating one if needed.

        One attempt, one unit of work. A concurrent creation surfaces as
        ``LinkConflictError`` for the caller to retry rather than being
        guessed at here.

        Args:
            original_url: The validated URL.
            url_hash: Its hash.
            scope: The scope to deduplicate within.
            owner_id_vo: Owner of the new link, or ``None`` for guests.
            guest_id: Identifier a guest's links are counted under.
            ttl_seconds: Time-to-live for a new link.
            log: Bound logger.
            audit: Bound audit logger.
            chosen_code: The code the caller asked for, or ``None`` to let
                the generator pick one.

        Returns:
            ShortLinkResponse DTO.

        Raises:
            LinkConflictError: If storing lost a race.
            LinkCodeTakenError: If ``chosen_code`` is one another link
                already carries. Not retried around: whoever asked for that
                code asked for that one.
            GuestLinkLimitExceededError: If the guest link limit is exceeded.
            CodeGenerationError: If no unique code could be generated.
        """
        cached_link = self.cache.get_by_hash(url_hash, scope)

        with self.uow_factory() as uow:
            existing_link = None
            from_cache = False

            if cached_link:
                existing_link = self._confirm(cached_link, url_hash, scope, uow)
                if existing_link:
                    from_cache = True
                    log.debug("Cache hit", hash=url_hash.value[:10])
                else:
                    # The entry outlived what it pointed at. Left in place it
                    # would go on offering the same dead code to every caller.
                    log.info(
                        "Dropping stale deduplication entry",
                        hash=url_hash.value[:10],
                        code=cached_link.short_code.value,
                    )
                    self.cache.delete(cached_link)

            # ---- Check repository ----------------------------
            if existing_link is None:
                existing_link = uow.links.find_live_by_hash(url_hash, scope)
                if existing_link:
                    log.debug("Found in repository", hash=url_hash.value[:10])
                    self.cache.save(existing_link)

            if existing_link:
                return self._build_response(
                    existing_link, from_cache=from_cache, is_new=False
                )

            # ---- Guest quota, charged only for a real creation ---
            # Asked after deduplication, not before: being handed back a
            # link that already exists creates nothing, so it cannot cost
            # anything. Charging first meant a guest who had spent their
            # allowance got 429 for a URL they had shortened themselves --
            # while the batch endpoint, asked the same question, answered
            # 200 with the very same link.
            if guest_id is not None:
                # One link is wanted, so any allowance at all is enough.
                # The batch path asks the same question and reads the
                # number instead, which is why the locking and the counting
                # behind it live on ``guest_allowance`` rather than here.
                if not guest_allowance(
                    uow.links, guest_id, self.guest_link_limit,
                    self.guest_link_window_days,
                ):
                    raise guest_quota_spent(
                        self.guest_link_limit, self.guest_link_window_days
                    )

            # ---- Pick a code and store -----------------------
            if chosen_code is not None:
                # A chosen code is not retried around. Whoever asked for it
                # asked for that one, and answering with another would look
                # like it worked; the free-code search exists for generated
                # codes, where any code will do.
                if uow.links.find_by_code(chosen_code) is not None:
                    raise LinkCodeTakenError(chosen_code.value)
                short_code = chosen_code
            else:
                short_code = self._generate_unique_code(original_url, uow, log)

            new_link = Link.create(
                url_hash=url_hash,
                short_code=short_code,
                original_url=original_url,
                owner=owner_id_vo,
                guest_identifier=guest_id,
                ttl_seconds=ttl_seconds,
            )

            saved_link = uow.links.save(new_link)
            uow.commit()

        # ---- Cache new link & audit --------------------------
        self.cache.save(saved_link)

        # The service totals just changed. Nothing dropped this key before,
        # so ``/api/v1/stats`` went on reporting the old count for the whole
        # CACHE_STATS_TTL -- five minutes in production, with a 200 and no
        # sign that it was answering from a stale snapshot.
        #
        # Only creation and deletion do this. Clicks are not counted here:
        # they arrive on every redirect, and dropping the key each time
        # would leave the cache with nothing to serve. Click totals lag by
        # the TTL, and that is what the TTL is for.
        self.stats_cache.delete_stats()

        log.info("Short link created successfully", short_code=short_code.value)

        audit.log_url_created(
            short_code=saved_link.short_code.value,
            original_url=saved_link.original_url.value,
        )

        return self._build_response(saved_link, from_cache=False, is_new=True)



    def _confirm(
        self,
        cached_link: Link,
        url_hash: UrlHash,
        scope: DedupScope,
        uow: UnitOfWork,
    ) -> Optional[Link]:
        """
        Check a cached deduplication hit against the database.

        The cache says a link existed under this hash when the entry was
        written; it cannot say whether it still does. Handing that claim
        straight to the client returned codes for links that had since been
        deleted or expired -- ``200 is_new=false`` followed by ``404`` or
        ``410`` on the code just issued.

        The confirmed entity is returned, not the cached copy: the database
        holds the current click count and expiry, and there is no reason to
        answer with an older copy of a row that was just read.

        Args:
            cached_link: What the cache offered.
            url_hash: Hash the lookup was made for.
            scope: Scope the lookup was made in.
            uow: Active Unit of Work.

        Returns:
            The stored link if it still backs the claim, otherwise ``None``.
        """
        stored = uow.links.find_by_code(cached_link.short_code)
        if stored is None:
            return None
        if stored.url_hash != url_hash:
            return None
        if stored.dedup_scope() != scope:
            return None
        if stored.is_expired():
            return None
        return stored

    def _generate_unique_code(self, original_url: OriginalUrl, uow: UnitOfWork, log: Logger) -> ShortCode:
        """
        Generate a unique short code, retrying on collisions.

        Args:
            original_url: The validated original URL.
            uow: Active Unit of Work for checking existence.
            log: Logger instance.

        Returns:
            A unique ShortCode value object.

        Raises:
            CodeGenerationError: If no unique code can be generated after max attempts.
        """
        for attempt in range(self.max_collision_attempts):
            code = self.code_generator.generate_unique(original_url, attempt)
            if not uow.links.find_by_code(code):
                return code

            log.debug("Code collision, retrying", attempt=attempt + 1, code=code.value)

        # The deterministic ladder is finite -- a URL has exactly as many
        # codes as there are attempts, and the same ones forever. One link per URL made that limit unreachable;
        # per-owner deduplication and expiry do not, so running out of rungs
        # is now an ordinary event and must not be a dead end.
        for attempt in range(self.max_collision_attempts):
            code = self.code_generator.generate_fresh(original_url)
            if not uow.links.find_by_code(code):
                log.info(
                    "Deterministic codes exhausted, issued a fresh one",
                    code=code.value,
                )
                return code

        raise CodeGenerationError()


    def _build_response(self, link: Link, from_cache: bool, is_new: bool) -> ShortLinkResponse:
        """
        Build a ShortLinkResponse DTO from a domain Link entity.

        Args:
            link: The domain Link object.
            from_cache: Whether the data came from cache.
            is_new: Whether the link was just created.

        Returns:
            ShortLinkResponse DTO ready for serialization.
        """
        return ShortLinkResponse.from_link(link, self.base_url, is_new=is_new, from_cache=from_cache)
