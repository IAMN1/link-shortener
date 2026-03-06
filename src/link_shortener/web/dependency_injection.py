
from link_shortener.domain import HashBasedShorteningPolicy

from link_shortener.application import (
    Logger, LinkCache, LinkService, BatchCreateLinksUseCase,
    CreateShortLinkUseCase, GetLinkInfoUseCase, GetServiceStatsUseCase,
    RedirectLinkUseCase, NullLogger, NullAuditLogger, NullCache
)

from link_shortener.infrastructure import (
    StructLogger, DatabaseManager, InMemoryLinkCache,
    RedisLinkCache, StructlogAuditLogger, 
    SQLAlchemyLinkRepository, FailoverLogger, StandartLogger
)



class Container:
    """
    Dependency injection container that manages all application components.

    Responsible for creating and wiring together repositories, caches,
    use cases, loggers, and the main LinkService.
    """

    def __init__(self, config):
        """
        Initialize the container with application configuration.

        Args:
            config (_type_): Application configuration object 
                (e.g., from ConfigFactory).
        """

        self.config = config
        self._logger = None
        self._audit_logger = None
        self._db_manager = None
        self._repository = None
        self._cache = None
        self._shortening_policy = None
        self._link_service = None
        self._use_cases = {}


    # =============== General dependencies ==================================
    def get_logger(self) -> Logger:
        """
        Get the application logger.

        If logging is disabled, returns NullLogger.
        Otherwise, creates a FailoverLogger that attempts to use
        StructLogger first, then StandardLogger, falling back to NullLogger.
        """

        if not self._logger:
            if not self.config.LOGGING_ENABLED:
                # Print warning because logger is disabled – we can't log it.
                print(
                    "WARNING: Logging is disabled. "
                    "All log messages will be discarded."
                )
                self._logger = NullLogger()
            else:
                # Создание всех возможных логеров в порядке предпочтения
                loggers = []

                # 1. StructLogger (Основной)
                try:

                    struct_logger = StructLogger("Link_shortener")
                    struct_logger.debug("Initializing structlog")
                    loggers.append((struct_logger, "structlog"))

                except Exception as e:
                    print(f"WARNING: Failed to initialize StructLogger: {e}")
                
                # 2. StandartLogger (резервный)
                try:

                    std_logger = StandartLogger("Link_shortener")
                    std_logger.debug("Initializing standard logger")
                    loggers.append((std_logger, "standart"))

                except Exception as e:
                    print(f"WARNING: Failed to initialize StandardLogger: {e}")
                
                # 3. NullLogger (всегда доступен)
                loggers.append((NullLogger(), "null"))

                if len(loggers) == 1: # only NullLogger
                    self._logger = NullLogger()
                else:
                    self._logger = FailoverLogger(loggers, check_interval=30.0)
        return self._logger

    def get_audit_logger(self) -> StructlogAuditLogger:
        """
        Get the audit logger for logging significant events (creation, access).
        If audit is disabled, returns NullAuditLogger.
        """

        if not self._audit_logger:
            if self.config.AUDIT_ENABLED:
                self._audit_logger = StructlogAuditLogger()
            else:
                self.get_logger().warning("Audit logging is disabled.")
                self._audit_logger = NullAuditLogger()
        return self._audit_logger

    def get_db_manager(self) -> DatabaseManager:
        """
        Get the database manager (handles connections and sessions).
        Creates and connects if not already done.
        """

        if not self._db_manager:
            self._db_manager = DatabaseManager(
                self.config.DATABASE_URL,
                echo=self.config.DEBUG
            )
            self._db_manager.connect()
        return self._db_manager

    def get_repository(self) -> SQLAlchemyLinkRepository:
        """
        Get the link repository (SQLAlchemy implementation).
        Uses the database manager for session handling.
        """

        if not self._repository:
            self._repository = SQLAlchemyLinkRepository(
                self.get_db_manager()
            )
        return self._repository

    def get_cache(self) -> LinkCache:
        """
        Get the cache implementation.

        - If caching is disabled, returns NullCache.
        - If Redis is enabled, attempts to create RedisLinkCache.
        - Otherwise, falls back to InMemoryLinkCache (for development).
        """

        if not self._cache:
            if not self.config.CACHE_ENABLED:
                self.get_logger().warning("Cache is disabled. Using NullCache.")
                self._cache = NullCache()

            elif self.config.REDIS_ENABLED:
                try:
                    self._cache = RedisLinkCache(
                        redis_url=self.config.REDIS_URL,
                        prefix=self.config.CACHE_LINK_PREFIX,
                        logger=self.get_logger(),
                        link_ttl=self.config.CACHE_LINK_TTL,
                        stats_ttl=self.config.CACHE_STATS_TTL
                    )
                except Exception as e:
                    self.get_logger().error(
                        f"Failed to initialize Redis cache: {e}. \
                        Falling back to NullCache."
                    )
                    self._cache = NullCache()
            else:
                self.get_logger().info("Using in-memory cache (development).")
                self._cache = InMemoryLinkCache(
                    prefix=self.config.CACHE_LINK_PREFIX,
                    link_ttl=self.config.CACHE_LINK_TTL,
                    stats_ttl=self.config.CACHE_STATS_TTL
                )
        return self._cache

    def get_shortening_policy(self) -> HashBasedShorteningPolicy:
        """
        Get the shortening policy (hash-based) 
            configured with length constraints."""

        if not self._shortening_policy:
            self._shortening_policy = HashBasedShorteningPolicy(
                code_length=self.config.SHORT_CODE_LENGTH,
                min_length=self.config.SHORT_CODE_MIN_LENGTH,
                max_length=self.config.SHORT_CODE_MAX_LENGTH
            )
        return self._shortening_policy


    # =============== Use cases =============================================
    def get_create_short_link_use_case(self) -> CreateShortLinkUseCase:
        """Get or create the CreateShortLinkUseCase instance."""

        if 'create' not in self._use_cases:
            self._use_cases['create'] = CreateShortLinkUseCase(
                repository=self.get_repository(),
                cache=self.get_cache(),
                shortening_policy=self.get_shortening_policy(),
                base_url=self.config.BASE_URL,
                logger=self.get_logger(),
                audit_logger=self.get_audit_logger()
            )
        return self._use_cases['create']

    def get_batch_create_links_use_case(self) -> BatchCreateLinksUseCase:
        """Get or create the BatchCreateLinksUseCase instance."""

        if 'batch' not in self._use_cases:
            self._use_cases['batch'] = BatchCreateLinksUseCase(
                repository=self.get_repository(),
                cache=self.get_cache(),
                shortening_policy=self.get_shortening_policy(),
                base_url=self.config.BASE_URL,
                logger=self.get_logger(),
                audit_logger=self.get_audit_logger(),
                batch_limit=self.config.BATCH_CREATE_LIMIT
            )
        return self._use_cases['batch']

    def get_get_link_info_use_case(self) -> GetLinkInfoUseCase:
        """Get or create the GetLinkInfoUseCase instance."""

        if 'info' not in self._use_cases:
            self._use_cases['info'] = GetLinkInfoUseCase(
                repository=self.get_repository(),
                cache=self.get_cache(),
                logger=self.get_logger(),
                base_url=self.config.BASE_URL,
            )
        return self._use_cases['info']

    def get_get_service_stats_use_case(self):
        """Get or create the GetServiceStatsUseCase instance."""

        if 'stats' not in self._use_cases:
            self._use_cases['stats'] = GetServiceStatsUseCase(
                repository=self.get_repository(),
                cache=self.get_cache(),
                logger=self.get_logger(),
                base_url=self.config.BASE_URL,
                cache_ttl=self.config.CACHE_STATS_TTL
            )
        return self._use_cases["stats"]

    def get_redirect_link_use_case(self) -> RedirectLinkUseCase:
        """Get or create the RedirectLinkUseCase instance."""

        if 'redirect' not in self._use_cases:
            self._use_cases['redirect'] = RedirectLinkUseCase(
                repository=self.get_repository(),
                link_cache=self.get_cache(),
                redirect_cache=self.get_cache(),
                logger=self.get_logger(),
                audit_logger=self.get_audit_logger()
            )
        return self._use_cases['redirect']


    # =============== Services =============================================
    def get_link_service(self) -> LinkService:
        """
        Get the main LinkService facade 
            that orchestrates all use cases.
        """

        if not self._link_service:
            self._link_service = LinkService(
                create_short_link_use_case=self.get_create_short_link_use_case(),
                get_link_info_use_case=self.get_get_link_info_use_case(),
                redirect_link_use_case=self.get_redirect_link_use_case(),
                batch_create_links_use_case=self.get_batch_create_links_use_case(),
                get_service_stats_use_case=self.get_get_service_stats_use_case()
            )
        return self._link_service

    def close(self):
        """Close all managed resources (database connections, etc)."""
        if self._db_manager:
            self._db_manager.close()
