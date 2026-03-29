from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.domain import HashBasedShorteningPolicy

from link_shortener.application import (
    Logger, LinkCache, LinkService, BatchCreateLinksUseCase,
    CreateShortLinkUseCase, GetLinkInfoUseCase, GetServiceStatsUseCase,
    GetExtendLinkInfoUseCase, RedirectLinkUseCase
)

from link_shortener.infrastructure import (
    DatabaseManager, InMemoryLinkCache, NullCache,
    RedisLinkCache, SQLAlchemyLinkRepository,
    AuditManager, LoggerManager
)



class Container:
    """
    Dependency injection container that manages all application components.

    Responsible for creating and wiring together repositories, caches,
    use cases, loggers, and the main LinkService.
    Components are created lazily (on first access) and cached.
    """

    def __init__(self, config):
        """
        Initialize the container with application configuration.

        Args:
            config: Application configuration object (e.g., from ConfigFactory).
        """

        self.config = config
        self._logger_manager = None
        self._audit_manager = None
        self._db_manager = None
        self._repository = None
        self._cache = None
        self._shortening_policy = None
        self._link_service = None
        self._use_cases = {}


    # =============== General dependencies ==================================
    def get_logger(self, module_name: str) -> Logger:
        """
        Get the application logger for a specific module.

        Delegates to the global LoggerManager. The logger type is determined
        by configuration (LOGGING_ENABLED and LOGGER_TYPE).

        Args:
            module_name: Name of the module requesting the logger (used for context).

        Returns:
            Logger instance.
        """
        if not self._logger_manager:
            # Determine effective logger type based on LOGGING_ENABLED flag
            if not self.config.LOGGING_ENABLED:
                effective_logger_type = "null"
            else:
                effective_logger_type = self.config.LOGGER_TYPE
            
            self._logger_manager = LoggerManager(
                logger_type=effective_logger_type,
                failover_check_interval=self.config.FAILOVER_CHECK_INTERVAL
            )
        return self._logger_manager.get_logger(module_name)

    def get_active_logger_name(self) -> str:
        """
        Get the name of the currently active logger (for monitoring).

        Returns:
            String like "structlog", "standard", "null", or "unknown".
        """
        if self._logger_manager:
            return self._logger_manager.get_active_logger_name()
        return "unknown"

    def get_audit_logger(self) -> AuditLogger:
        """
        Get the audit logger for logging significant events (creation, access).

        Delegates to the global AuditManager. The audit type is determined
        by configuration (AUDIT_ENABLED and AUDIT_TYPE).

        Returns:
            AuditLogger instance.
        """
        if not self._audit_manager:
            # Determine effective audit type based on AUDIT_ENABLED flag
            if not self.config.AUDIT_ENABLED:
                effective_audit_type = "null"
            else:
                effective_audit_type = self.config.AUDIT_TYPE
            
            self._audit_manager = AuditManager(
                audit_type=effective_audit_type,
                failover_check_interval=self.config.FAILOVER_CHECK_INTERVAL
            )
        return self._audit_manager.get_audit_logger()

    def get_db_manager(self) -> DatabaseManager:
        """
        Get the database manager (handles connections and sessions).

        Creates and connects if not already done.

        Returns:
            DatabaseManager instance.
        """

        if not self._db_manager:
            self._db_manager = DatabaseManager(
                database_url=self.config.get_database_url(),
                echo=self.config.SQLALCHEMY_ECHO,
                database_type=self.config.DATABASE_TYPE,
                **self.config.get_pool_params()
            )
            self._db_manager.connect()
        return self._db_manager

    def get_repository(self) -> SQLAlchemyLinkRepository:
        """
        Get the link repository (SQLAlchemy implementation).

        Uses the database manager for session handling.

        Returns:
            SQLAlchemyLinkRepository instance.
        """

        if not self._repository:
            self._repository = SQLAlchemyLinkRepository(
                self.get_db_manager()
            )
        return self._repository

    def get_cache(self) -> LinkCache:
        """
        Get the cache implementation based on configuration.

        Rules:
          - If caching is disabled, returns NullCache.
          - If Redis is enabled, attempts to create RedisLinkCache; on failure falls back to NullCache.
          - Otherwise, returns InMemoryLinkCache (for development).

        Returns:
            LinkCache instance (may be NullCache).
        """

        if not self._cache:
            if not self.config.CACHE_ENABLED:
                self.get_logger(Container.__module__).warning(
                    "Cache is disabled. Using NullCache."
                )
                self._cache = NullCache()

            elif self.config.REDIS_ENABLED:
                try:
                    self._cache = RedisLinkCache(
                        redis_url=self.config.REDIS_URL,
                        prefix=self.config.CACHE_LINK_PREFIX,
                        logger=self.get_logger(RedisLinkCache.__module__),
                        link_ttl=self.config.CACHE_LINK_TTL,
                        stats_ttl=self.config.CACHE_STATS_TTL,
                        connect_timeout=self.config.REDIS_CONNECT_TIMEOUT,
                        socket_timeout=self.config.REDIS_SOCKET_TIMEOUT,
                        retry_interval=self.config.REDIS_RETRY_INTERVAL
                    )
                except Exception as e:
                    self.get_logger(Container.__module__).error(
                        "Failed to initialize Redis cache. Falling back to NullCache.",
                        error=str(e),
                        exc_info=True
                    )
                    self._cache = NullCache()
            else:
                self.get_logger(Container.__module__).info(
                    "Using in-memory cache (development)."
                )
                self._cache = InMemoryLinkCache(
                    prefix=self.config.CACHE_LINK_PREFIX,
                    link_ttl=self.config.CACHE_LINK_TTL,
                    stats_ttl=self.config.CACHE_STATS_TTL
                )
        return self._cache

    def get_shortening_policy(self) -> HashBasedShorteningPolicy:
        """
        Get the shortening policy (hash-based) configured with length constraints.

        Returns:
            HashBasedShorteningPolicy instance.
        """

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
                logger=self.get_logger(CreateShortLinkUseCase.__module__),
                audit_logger=self.get_audit_logger(),
                allowed_schemes=self.config.ALLOWED_SCHEMES,
                max_collision_attempts=self.config.MAX_COLLISION_ATTEMPTS
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
                logger=self.get_logger(BatchCreateLinksUseCase.__module__),
                audit_logger=self.get_audit_logger(),
                allowed_schemes=self.config.ALLOWED_SCHEMES,
                batch_limit=self.config.BATCH_CREATE_LIMIT
            )
        return self._use_cases['batch']

    def get_get_link_info_use_case(self) -> GetLinkInfoUseCase:
        """Get or create the GetLinkInfoUseCase instance."""

        if 'info' not in self._use_cases:
            self._use_cases['info'] = GetLinkInfoUseCase(
                repository=self.get_repository(),
                cache=self.get_cache(),
                logger=self.get_logger(GetLinkInfoUseCase.__module__),
                base_url=self.config.BASE_URL,
            )
        return self._use_cases['info']

    def get_extended_link_info_use_case(self) -> GetExtendLinkInfoUseCase:
        """Get or create the GetExtendLinkInfoUseCase instance."""
        if 'extended_info' not in self._use_cases:
            self._use_cases['extended_info'] = GetExtendLinkInfoUseCase(
                repository=self.get_repository(),
                cache=self.get_cache(),
                logger=self.get_logger(GetExtendLinkInfoUseCase.__module__),
                base_url=self.config.BASE_URL,
                popular_threshold=self.config.POPULAR_THRESHOLD,
                recent_days=self.config.RECENT_DAYS
            )
        return self._use_cases['extended_info']

    def get_get_service_stats_use_case(self):
        """Get or create the GetServiceStatsUseCase instance."""

        if 'stats' not in self._use_cases:
            self._use_cases['stats'] = GetServiceStatsUseCase(
                repository=self.get_repository(),
                cache=self.get_cache(),
                logger=self.get_logger(GetServiceStatsUseCase.__module__),
                base_url=self.config.BASE_URL,
            )
        return self._use_cases["stats"]

    def get_redirect_link_use_case(self) -> RedirectLinkUseCase:
        """Get or create the RedirectLinkUseCase instance."""

        if 'redirect' not in self._use_cases:
            self._use_cases['redirect'] = RedirectLinkUseCase(
                repository=self.get_repository(),
                link_cache=self.get_cache(),
                redirect_cache=self.get_cache(),
                logger=self.get_logger(RedirectLinkUseCase.__module__),
                audit_logger=self.get_audit_logger()
            )
        return self._use_cases['redirect']


    # =============== Services =============================================
    def get_link_service(self) -> LinkService:
        """
        Get the main LinkService facade that orchestrates all use cases.

        Returns:
            LinkService instance.
        """

        if not self._link_service:
            self._link_service = LinkService(
                create_short_link_use_case=self.get_create_short_link_use_case(),
                get_link_info_use_case=self.get_get_link_info_use_case(),
                get_extended_link_info_use_case=self.get_extended_link_info_use_case(),
                redirect_link_use_case=self.get_redirect_link_use_case(),
                batch_create_links_use_case=self.get_batch_create_links_use_case(),
                get_service_stats_use_case=self.get_get_service_stats_use_case()
            )
        return self._link_service

    def close(self):
        """
        Close all managed resources (database connections, cache connections, etc.)

        Should be called when the application shuts down.
        """
        if self._db_manager:
            self._db_manager.close()
        if self._cache and hasattr(self._cache, 'close'):
            self._cache.close()
        if self._logger_manager:
            self._logger_manager.shutdown()
        if self._audit_manager:
            self._audit_manager.shutdown()
