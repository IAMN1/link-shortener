"""
Root Dependency Injection container for the link shortener application.

This module provides the ``Container`` class which wires together all
infrastructure components, use cases, and application services.  Dependencies
are created lazily to avoid unnecessary initialisation at import time.
"""


from typing import Optional

from link_shortener.application import (
    UnitOfWork, RoleManagementService,
    UserManagementService, LinkService,
    AdminService,
    # Named here because every public accessor below says what it hands out:
    # a container whose getters return an unannotated value makes everything
    # it builds ``Any`` at the call site, however carefully the components
    # themselves are typed.
    ActivateUserUseCase, AuditLogger, BatchCreateLinksUseCase,
    ChangePasswordUseCase,
    CleanExpiredLinksUseCase, CleanUnverifiedAccountsUseCase,
    CreateRoleUseCase, CreateShortLinkUseCase, CreateUserUseCase,
    ConfirmUserEmailUseCase, DeactivateUserUseCase, DeleteLinkUseCase,
    DeleteRoleUseCase,
    DeleteUserUseCase, GetExtendedLinkInfoUseCase, GetLinkInfoUseCase,
    GetRecentLinksUseCase, GetRoleUseCase, GetServiceHealthUseCase,
    GetServiceStatsUseCase, GetVisitStatsUseCase,
    GetUserActivityStatsUseCase, GetUserLinksUseCase,
    GetUserUseCase, ListRolesUseCase, ListUsersUseCase, Logger, LoginUseCase,
    Mailer, RateLimiter, ReadJournalUseCase, RedirectLinkUseCase, RegisterUseCase,
    RequestPasswordResetUseCase,
    ResendVerificationUseCase, ResetPasswordUseCase, RollUpSecurityEventsUseCase,
    RollUpVisitsUseCase, SeedDatabaseUseCase,
    SendAccountExistsEmailUseCase, SendPasswordResetEmailUseCase,
    SendVerificationEmailUseCase, ServiceCache,
    TaskQueue, UnitOfWorkFactory, UpdateLinkStatsUseCase,
    UpdateRolePermissionsUseCase, UpdateUserRolesUseCase, VerifyEmailUseCase,
)

from link_shortener.infrastructure.auth.jwt_auth_service import (
    JwtAuthenticationService,
)
from link_shortener.infrastructure.auth.rbac_authorization_service import (
    RBACAuthorizationService,
)
from link_shortener.infrastructure.configs.app.base import BaseConfig
from link_shortener.infrastructure.database.manager import DatabaseManager
from link_shortener.infrastructure.database.unit_of_work import SQLAlchemyUnitOfWork
from link_shortener.infrastructure.di.components.logger import LoggerComponent
from link_shortener.infrastructure.logging.status_reader import (
    ComponentLoggingStatus,
)
from link_shortener.application.use_cases.security.get_security_counts import (
    GetSecurityCountsUseCase,
)
from link_shortener.infrastructure.logging.handlers.audit.counting import (
    CountingAuditLogger,
)
from link_shortener.infrastructure.di.components.audit import AuditComponent
from link_shortener.infrastructure.di.components.database import DatabaseComponent
from link_shortener.infrastructure.di.components.cache import CacheComponent
from link_shortener.infrastructure.di.components.mail import MailComponent
from link_shortener.infrastructure.di.components.policy import PolicyComponent
from link_shortener.infrastructure.di.components.rate_limiter import RateLimiterComponent
from link_shortener.infrastructure.di.components.task_queue import TaskQueueComponent
from link_shortener.infrastructure.di.components.auth import AuthComponent
from link_shortener.infrastructure.di.components.use_cases.health.health_use_cases import HealthUseCasesComponent
from link_shortener.infrastructure.di.components.use_cases.journals.journal_use_cases import JournalUseCasesComponent
from link_shortener.infrastructure.di.components.use_cases.link.link_use_cases import LinkUseCasesComponent
from link_shortener.infrastructure.di.components.use_cases.link.batch_use_cases import BatchUseCasesComponent
from link_shortener.infrastructure.di.components.use_cases.stats.stats_use_cases import StatsUseCasesComponent
from link_shortener.infrastructure.di.components.use_cases.admin.admin_link_use_cases import AdminLinkUseCasesComponent
from link_shortener.infrastructure.di.components.use_cases.admin.admin_role_use_cases import AdminRoleUseCasesComponent
from link_shortener.infrastructure.di.components.use_cases.admin.admin_user_use_cases import AdminUserUseCasesComponent
from link_shortener.infrastructure.di.components.use_cases.authentication.auth_use_cases import AuthUseCasesComponent
from link_shortener.infrastructure.health.infrastructure_health_check import InfrastructureHealthCheck
from link_shortener.infrastructure.mail.jinja_templates import JinjaMailTemplates



class Container:
    """
    Root DI container for the link shortener application.

    All dependencies are created lazily. The container provides:

    * Public accessors for use cases.
    * Public accessors for application services.
    * Public accessors for cross-cutting infrastructure (cache, logger, etc.).

    Lifecycle:
        ``close()`` must be called at shutdown to release resources (database
        connections, cache connections, logger/audit failover threads).
    """
    def __init__(self, config: BaseConfig):
        """
        Args:
            config: An application config object (e.g. ``BaseConfig`` instance)
                providing all settings needed by the components.
        """
        self.config = config

        # ------------------------------------------------------------------
        # Cross‑cutting components
        # ------------------------------------------------------------------
        self.logger_component = LoggerComponent(
            logging_enabled=self.config.LOGGING_ENABLED,
            logger_type=self.config.LOGGER_TYPE,
            failover_check_interval=self.config.FAILOVER_CHECK_INTERVAL,
        )
        self._counting_audit: Optional[CountingAuditLogger] = None
        self.audit_component = AuditComponent(
            audit_enabled=self.config.AUDIT_ENABLED,
            audit_type=self.config.AUDIT_TYPE,
            failover_check_interval=self.config.FAILOVER_CHECK_INTERVAL,
        )

        # ------------------------------------------------------------------
        # Database
        # ------------------------------------------------------------------
        self.db_component = DatabaseComponent(
            database_url=self.config.get_database_url(),
            echo=self.config.SQLALCHEMY_ECHO,
            # The backend of the URL being opened, not the setting that
            # says how to assemble one: DATABASE_TYPE is not read at all
            # once DATABASE_URL is set, and it defaults to sqlite -- so a
            # deployment that named PostgreSQL in DATABASE_URL alone got
            # an engine configured for SQLite against a PostgreSQL server.
            db_type=self.config.database_backend(),
            pool_params=self.config.get_pool_params(),
            connect_timeout=self.config.DATABASE_CONNECT_TIMEOUT,
            statement_timeout=self.config.DATABASE_STATEMENT_TIMEOUT,
        )

        # ------------------------------------------------------------------
        # Domain policy implementations
        # ------------------------------------------------------------------
        self.policy_component = PolicyComponent(
            code_length=self.config.SHORT_CODE_LENGTH,
            min_length=self.config.SHORT_CODE_MIN_LENGTH,
            max_length=self.config.SHORT_CODE_MAX_LENGTH,
            pepper=self.config.SHORT_CODE_SECRET_PEPPER,
        )

        # ------------------------------------------------------------------
        # Rate limiting
        # ------------------------------------------------------------------
        self.rate_limiter_component = RateLimiterComponent(
            redis_enabled=self.config.REDIS_ENABLED,
            redis_url=self.config.REDIS_URL,
            connect_timeout=self.config.REDIS_CONNECT_TIMEOUT,
            socket_timeout=self.config.REDIS_SOCKET_TIMEOUT,
            logger=self.logger_component.get_logger(__name__),
            retry_interval=self.config.REDIS_RETRY_INTERVAL,
        )

        # ------------------------------------------------------------------
        # Task queue
        # ------------------------------------------------------------------
        self.task_queue_component = TaskQueueComponent(
            celery_enabled=self.config.CELERY_ENABLED,
            logger=self.logger_component.get_logger(__name__),
            retry_interval=self.config.REDIS_RETRY_INTERVAL,
        )

        # ------------------------------------------------------------------
        # Mail
        # ------------------------------------------------------------------
        self.mail_component = MailComponent(
            mail_enabled=self.config.MAIL_ENABLED,
            host=self.config.MAIL_HOST,
            port=self.config.MAIL_PORT,
            username=self.config.MAIL_USERNAME,
            password=self.config.MAIL_PASSWORD,
            sender=self.config.MAIL_FROM,
            use_tls=self.config.MAIL_USE_TLS,
            use_ssl=self.config.MAIL_USE_SSL,
            timeout=self.config.MAIL_TIMEOUT,
            logger=self.logger_component.get_logger(__name__),
        )

        # ------------------------------------------------------------------
        # Cache
        # ------------------------------------------------------------------
        self.cache_component = CacheComponent(
            cache_enabled=self.config.CACHE_ENABLED,
            redis_enabled=self.config.REDIS_ENABLED,
            redis_url=self.config.REDIS_URL,
            link_prefix=self.config.CACHE_LINK_PREFIX,
            link_ttl=self.config.CACHE_LINK_TTL,
            stats_ttl=self.config.CACHE_STATS_TTL,
            connect_timeout=self.config.REDIS_CONNECT_TIMEOUT,
            socket_timeout=self.config.REDIS_SOCKET_TIMEOUT,
            retry_interval=self.config.REDIS_RETRY_INTERVAL,
            logger=self.logger_component.get_logger(__name__),
            secret_key=self.config.SECRET_KEY,
        )

        # ------------------------------------------------------------------
        # Health checker
        # ------------------------------------------------------------------
        self.health_check = InfrastructureHealthCheck(
            db_manager=self.db_component.get_db_manager(),
            cache=self.cache_component.get_cache(),
            task_queue=self.task_queue_component.get_task_queue(),
            timeout=self.config.HEALTH_CHECK_TIMEOUT,
            rate_limiter=self.rate_limiter_component.get_rate_limiter(),
        )

        # ------------------------------------------------------------------
        # Unit of Work factory (created once, shared across components)
        # ------------------------------------------------------------------
        def uow_factory(read_only: bool = False) -> UnitOfWork:
            return SQLAlchemyUnitOfWork(
                self.db_component.get_db_manager(),
                read_only=read_only,
                # Named after the unit of work that owns it rather than
                # after this module, so a warning from one of its
                # repositories is filed under the database layer instead
                # of under the container that wired it together.
                logger=self.logger_component.get_logger(
                    SQLAlchemyUnitOfWork.__module__
                ),
            )

        self._uow_factory = uow_factory

        # ------------------------------------------------------------------
        # Auth services
        # ------------------------------------------------------------------
        self.auth_component = AuthComponent(
            secret_key=self.config.SECRET_KEY,
            jwt_access_expire_minutes=self.config.JWT_ACCESS_TOKEN_EXPIRE_MINUTES,
            jwt_refresh_expire_days=self.config.JWT_REFRESH_TOKEN_EXPIRE_DAYS,
            jwt_algorithm=self.config.JWT_ALGORITHM,
            uow_factory=self._uow_factory,
            logger=self.logger_component.get_logger(__name__),
        )

        # ------------------------------------------------------------------
        # Application services (plain objects, no external dependencies)
        # ------------------------------------------------------------------
        self._role_management_service = RoleManagementService()
        self._user_management_service = UserManagementService(
            authentication_service=self.auth_component.get_authentication_service(),
            default_role_name=self.config.DEFAULT_ROLE_NAME,
        )

        # ------------------------------------------------------------------
        # Use‑case component caches (lazy initialisation)
        # ------------------------------------------------------------------
        # Annotated Optional rather than inferred from these assignments: each
        # holds None until the matching ``_init_`` builds it, and a checker
        # told otherwise reports both the assignment and the return as errors.
        self._link_use_cases: Optional[LinkUseCasesComponent] = None
        self._batch_use_cases: Optional[BatchUseCasesComponent] = None
        self._stats_use_cases: Optional[StatsUseCasesComponent] = None
        self._admin_link_use_cases: Optional[AdminLinkUseCasesComponent] = None
        self._admin_role_use_cases: Optional[AdminRoleUseCasesComponent] = None
        self._admin_user_use_cases: Optional[AdminUserUseCasesComponent] = None
        self._auth_use_cases: Optional[AuthUseCasesComponent] = None
        self._user_activity_stats_uc: Optional[GetUserActivityStatsUseCase] = None
        self._health_use_cases: Optional[HealthUseCasesComponent] = None
        self._journal_use_cases: Optional[JournalUseCasesComponent] = None

        # ------------------------------------------------------------------
        # Facade service for Link operations (eagerly composed)
        # ------------------------------------------------------------------
        self._link_service = LinkService(
            create_short_link_use_case=self.get_create_short_link_use_case(),
            get_link_info_use_case=self.get_get_link_info_use_case(),
            get_extended_link_info_use_case=self.get_extended_link_info_use_case(),
            redirect_link_use_case=self.get_redirect_link_use_case(),
            batch_create_links_use_case=self.get_batch_create_links_use_case(),
            get_service_stats_use_case=self.get_get_service_stats_use_case(),
            get_visit_stats_use_case=self.get_visit_stats_use_case(),
            get_user_links_use_case=self.get_get_user_links_use_case(),
            delete_link_use_case=self.get_delete_link_use_case(),
        )

        # ------------------------------------------------------------------
        # Facade service for Admin operations (eagerly composed)
        # ------------------------------------------------------------------
        self._admin_service = AdminService(
            create_user_uc=self.get_create_user_use_case(),
            update_user_roles_uc=self.get_update_user_roles_use_case(),
            confirm_user_email_uc=self.get_confirm_user_email_use_case(),
            resend_verification_uc=self.get_resend_verification_use_case(),
            deactivate_user_uc=self.get_deactivate_user_use_case(),
            activate_user_uc=self.get_activate_user_use_case(),
            list_users_uc=self.get_list_users_use_case(),
            get_user_uc=self.get_get_user_use_case(),
            delete_user_uc=self.get_delete_user_use_case(),
            create_role_uc=self.get_create_role_use_case(),
            update_role_permissions_uc=self.get_update_role_permissions_use_case(),
            delete_role_uc=self.get_delete_role_use_case(),
            list_roles_uc=self.get_list_roles_use_case(),
            get_role_uc=self.get_get_role_use_case(),
            get_service_health_uc=self.get_service_health_use_case(),
            get_user_activity_stats_uc=self.get_user_activity_stats_use_case(),
        )

    # ------------------------------------------------------------------
    # Lazy initialisers for use‑case component groups
    # ------------------------------------------------------------------
    def _init_link_use_cases(self) -> LinkUseCasesComponent:
        """Ensure ``LinkUseCasesComponent`` is created and return it."""
        if self._link_use_cases is None:
            self._link_use_cases = LinkUseCasesComponent(
                uow_factory=self._uow_factory,
                cache=self.cache_component.get_cache(),
                redirect_cache=self.cache_component.get_cache(),
                hash_calculator=self.policy_component.get_hash_calculator(),
                code_generator=self.policy_component.get_code_generator(),
                base_url=self.config.BASE_URL,
                logger=self.logger_component.get_logger(__name__),
                audit_logger=self._audit_logger(),
                task_queue=self.task_queue_component.get_task_queue(),
                allowed_schemes=self.config.ALLOWED_SCHEMES,
                max_url_length=self.config.MAX_URL_LENGTH,
                allow_internal_targets=self.config.ALLOW_INTERNAL_TARGETS,
                max_collision_attempts=self.config.MAX_COLLISION_ATTEMPTS,
                popular_threshold=self.config.POPULAR_THRESHOLD,
                recent_days=self.config.RECENT_DAYS,
                guest_link_limit=self.config.GUEST_LINK_LIMIT,
                guest_link_window_days=self.config.GUEST_LINK_WINDOW_DAYS,
                default_guest_ttl_seconds=self.config.DEFAULT_GUEST_TTL_SECONDS,
                max_ttl_seconds=self.config.MAX_TTL_SECONDS,
                authorization_service=self.auth_component.get_authorization_service(),
                record_visits=self.config.VISIT_TRACKING_ENABLED,
            )
            # Wire synchronous fallback for NullTaskQueue
            if not self.config.CELERY_ENABLED:
                update_uc = self._link_use_cases.get_update_link_stats_use_case()
                self.task_queue_component.set_update_stats_fn(update_uc.execute)
        return self._link_use_cases

    def _init_batch_use_cases(self) -> BatchUseCasesComponent:
        """Ensure ``BatchUseCasesComponent`` is created and return it."""
        if self._batch_use_cases is None:
            self._batch_use_cases = BatchUseCasesComponent(
                uow_factory=self._uow_factory,
                cache=self.cache_component.get_cache(),
                stats_cache=self.cache_component.get_cache(),
                hash_calculator=self.policy_component.get_hash_calculator(),
                code_generator=self.policy_component.get_code_generator(),
                base_url=self.config.BASE_URL,
                logger=self.logger_component.get_logger(__name__),
                audit_logger=self._audit_logger(),
                allowed_schemes=self.config.ALLOWED_SCHEMES,
                max_url_length=self.config.MAX_URL_LENGTH,
                allow_internal_targets=self.config.ALLOW_INTERNAL_TARGETS,
                max_collision_attempts=self.config.MAX_COLLISION_ATTEMPTS,
                batch_limit=self.config.BATCH_CREATE_LIMIT,
                guest_link_limit=self.config.GUEST_LINK_LIMIT,
                guest_link_window_days=self.config.GUEST_LINK_WINDOW_DAYS,
                default_guest_ttl_seconds=self.config.DEFAULT_GUEST_TTL_SECONDS,
            )
        return self._batch_use_cases

    def _init_stats_use_cases(self) -> StatsUseCasesComponent:
        """Ensure ``StatsUseCasesComponent`` is created and return it."""
        if self._stats_use_cases is None:
            self._stats_use_cases = StatsUseCasesComponent(
                uow_factory=self._uow_factory,
                cache=self.cache_component.get_cache(),
                base_url=self.config.BASE_URL,
                logger=self.logger_component.get_logger(__name__),
            )
        return self._stats_use_cases

    def _init_admin_link_use_cases(self) -> AdminLinkUseCasesComponent:
        """Ensure ``AdminLinkUseCasesComponent`` is created and return it."""
        if self._admin_link_use_cases is None:
            self._admin_link_use_cases = AdminLinkUseCasesComponent(
                uow_factory=self._uow_factory,
                cache=self.cache_component.get_cache(),
                logger=self.logger_component.get_logger(__name__),
                create_short_link_use_case=self.get_create_short_link_use_case(),
                visit_retention_days=self.config.VISIT_RETENTION_DAYS,
            )
        return self._admin_link_use_cases

    def _init_admin_role_use_cases(self) -> AdminRoleUseCasesComponent:
        """Ensure ``AdminRoleUseCasesComponent`` is created and return it."""
        if self._admin_role_use_cases is None:
            self._admin_role_use_cases = AdminRoleUseCasesComponent(
                uow_factory=self._uow_factory,
                role_service=self._role_management_service,
                logger=self.logger_component.get_logger(__name__),
                audit_logger=self._audit_logger(),
            )
        return self._admin_role_use_cases

    def _init_admin_user_use_cases(self) -> AdminUserUseCasesComponent:
        """Ensure ``AdminUserUseCasesComponent`` is created and return it."""
        if self._admin_user_use_cases is None:
            self._admin_user_use_cases = AdminUserUseCasesComponent(
                uow_factory=self._uow_factory,
                user_service=self._user_management_service,
                cache=self.cache_component.get_cache(),
                redirect_cache=self.cache_component.get_cache(),
                stats_cache=self.cache_component.get_cache(),
                logger=self.logger_component.get_logger(__name__),
                audit_logger=self._audit_logger(),
            )
        return self._admin_user_use_cases

    def _audit_logger(self) -> AuditLogger:
        """
        The audit logger every use case is given, counting as it writes.

        Wrapped once here rather than in ``AuditComponent``: the component
        builds loggers out of configuration and knows nothing about a
        database, while the counting half needs a unit of work. Wrapping at
        the seam keeps the layering and means no use case is aware that its
        events are counted at all.

        Returns:
            The wrapped logger, built once and reused.
        """
        if self._counting_audit is None:
            self._counting_audit = CountingAuditLogger(
                inner=self.audit_component.get_audit_logger(),
                uow_factory=self._uow_factory,
                logger=self.logger_component.get_logger(__name__),
            )
        return self._counting_audit

    def _init_auth_use_cases(self) -> AuthUseCasesComponent:
        """Ensure ``AuthUseCasesComponent`` is created and return it."""
        if self._auth_use_cases is None:
            self._auth_use_cases = AuthUseCasesComponent(
                uow_factory=self._uow_factory,
                authentication_service=self.auth_component.get_authentication_service(),
                user_service=self._user_management_service,
                logger=self.logger_component.get_logger(__name__),
                audit_logger=self._audit_logger(),
                default_role_name=self.config.DEFAULT_ROLE_NAME,
                task_queue=self.task_queue_component.get_task_queue(),
                mailer=self.mail_component.get_mailer(),
                templates=JinjaMailTemplates(),
                base_url=self.config.BASE_URL,
                verification_ttl_hours=self.config.EMAIL_VERIFICATION_TTL_HOURS,
                password_reset_ttl_minutes=self.config.PASSWORD_RESET_TTL_MINUTES,
                unverified_ttl_hours=self.config.UNVERIFIED_ACCOUNT_TTL_HOURS,
            )
            # Wire the synchronous fallback for NullTaskQueue, the same way
            # the click counter is wired. Without a broker the message is
            # sent on the request thread, which is slower and still sends.
            if not self.config.CELERY_ENABLED:
                send_uc = self._auth_use_cases.get_send_verification_email_use_case()
                self.task_queue_component.set_send_verification_fn(send_uc.execute)
                # Wired for the same reason and in the same breath: if the
                # notice were only sent when a broker happens to be
                # configured, registration would take one length with
                # Celery on and two lengths with it off.
                # And the reset message, for the third time and the
                # same reason. Left unwired, `forgot-password` would take
                # the token, store it, answer 202 and send nothing --
                # which is indistinguishable, from outside, from an
                # address nobody registered.
                reset_uc = (
                    self._auth_use_cases.get_send_password_reset_email_use_case()
                )
                self.task_queue_component.set_send_password_reset_fn(
                    reset_uc.execute
                )
                exists_uc = (
                    self._auth_use_cases.get_send_account_exists_email_use_case()
                )
                self.task_queue_component.set_send_account_exists_fn(
                    exists_uc.execute
                )
        return self._auth_use_cases

    def _init_health_use_cases(self) -> HealthUseCasesComponent:
        """Ensure ``HealthUseCasesComponent`` is created and return it."""
        if self._health_use_cases is None:
            self._health_use_cases = HealthUseCasesComponent(
                health_check=self.health_check,
                logger=self.logger_component.get_logger(__name__),
                logging_status=ComponentLoggingStatus(
                    self.logger_component, self.audit_component
                ),
            )
        return self._health_use_cases

    def _init_journal_use_cases(self) -> JournalUseCasesComponent:
        """Ensure ``JournalUseCasesComponent`` is created and return it."""
        if self._journal_use_cases is None:
            self._journal_use_cases = JournalUseCasesComponent(
                # The same four settings the logging handlers are built
                # from, read here again rather than asked of the handlers:
                # a deployment that writes nowhere -- ``LOGGING_ENABLED``
                # off, or a null logger -- still has a directory where the
                # journals would be, and the reader is expected to answer
                # "nothing there" rather than to fail to be built.
                log_dir=self.config.LOG_DIR,
                log_filename=self.config.LOG_FILENAME,
                audit_log_filename=self.config.AUDIT_LOG_FILENAME,
                error_log_filename=self.config.ERROR_LOG_FILENAME,
                authorization_service=self.auth_component.get_authorization_service(),
                uow_factory=self._uow_factory,
                logger=self.logger_component.get_logger(__name__),
                audit_logger=self._audit_logger(),
            )
        return self._journal_use_cases

    # ------------------------------------------------------------------
    # Public use case accessors
    # ------------------------------------------------------------------
    def get_create_short_link_use_case(self) -> CreateShortLinkUseCase:
        """Return fully configured ``CreateShortLinkUseCase``."""
        return self._init_link_use_cases().get_create_short_link_use_case()

    def get_get_link_info_use_case(self) -> GetLinkInfoUseCase:
        """Return fully configured ``GetLinkInfoUseCase``."""
        return self._init_link_use_cases().get_get_link_info_use_case()

    def get_extended_link_info_use_case(self) -> GetExtendedLinkInfoUseCase:
        """Return fully configured ``GetExtendedLinkInfoUseCase``."""
        return self._init_link_use_cases().get_extended_link_info_use_case()

    def get_redirect_link_use_case(self) -> RedirectLinkUseCase:
        """Return fully configured ``RedirectLinkUseCase``."""
        return self._init_link_use_cases().get_redirect_link_use_case()

    def get_update_link_stats_use_case(self) -> UpdateLinkStatsUseCase:
        """Return fully configured ``UpdateLinkStatsUseCase`` (for background tasks)."""
        return self._init_link_use_cases().get_update_link_stats_use_case()

    def get_delete_link_use_case(self) -> DeleteLinkUseCase:
        """Return fully configured ``DeleteLinkUseCase``."""
        return self._init_link_use_cases().get_delete_link_use_case()

    def get_batch_create_links_use_case(self) -> BatchCreateLinksUseCase:
        """Return fully configured ``BatchCreateLinksUseCase``."""
        return self._init_batch_use_cases().get_batch_create_links_use_case()

    def get_get_service_stats_use_case(self) -> GetServiceStatsUseCase:
        """Return fully configured ``GetServiceStatsUseCase``."""
        return self._init_stats_use_cases().get_get_service_stats_use_case()

    def get_visit_stats_use_case(self) -> GetVisitStatsUseCase:
        """Return fully configured ``GetVisitStatsUseCase``."""
        return self._init_stats_use_cases().get_visit_stats_use_case()

    # Admin link use cases
    def get_roll_up_visits_use_case(self) -> RollUpVisitsUseCase:
        """Return fully configured ``RollUpVisitsUseCase``."""
        return self._init_admin_link_use_cases().get_roll_up_visits_use_case()

    def get_security_counts_use_case(self) -> GetSecurityCountsUseCase:
        """Return fully configured ``GetSecurityCountsUseCase``.

        Built here for the reason the roll-up is: a unit of work, the
        authorization service and a logger, and nothing a component would
        add beyond a file to keep in step.
        """
        return GetSecurityCountsUseCase(
            uow_factory=self._uow_factory,
            authorization_service=(
                self.auth_component.get_authorization_service()
            ),
            logger=self.logger_component.get_logger(__name__),
        )

    def get_roll_up_security_events_use_case(
        self,
    ) -> RollUpSecurityEventsUseCase:
        """Return fully configured ``RollUpSecurityEventsUseCase``.

        Built here rather than in a component of its own: it needs a unit
        of work, a logger and one setting, and a component holding nothing
        else would be a file to keep in step for no gain.
        """
        return RollUpSecurityEventsUseCase(
            uow_factory=self._uow_factory,
            logger=self.logger_component.get_logger(__name__),
            retention_days=self.config.SECURITY_EVENT_RETENTION_DAYS,
        )

    def get_clean_expired_links_use_case(self) -> CleanExpiredLinksUseCase:
        """Return fully configured ``CleanExpiredLinksUseCase``."""
        return self._init_admin_link_use_cases().get_clean_expired_links_use_case()

    def get_get_recent_links_use_case(self) -> GetRecentLinksUseCase:
        """Return fully configured ``GetRecentLinksUseCase``."""
        return self._init_admin_link_use_cases().get_get_recent_links_use_case()

    def get_seed_database_use_case(self) -> SeedDatabaseUseCase:
        """Return fully configured ``SeedDatabaseUseCase``."""
        return self._init_admin_link_use_cases().get_seed_database_use_case()

    # Role management use cases
    def get_create_role_use_case(self) -> CreateRoleUseCase:
        """Return fully configured ``CreateRoleUseCase``."""
        return self._init_admin_role_use_cases().get_create_role_use_case()

    def get_update_role_permissions_use_case(self) -> UpdateRolePermissionsUseCase:
        """Return fully configured ``UpdateRolePermissionsUseCase``."""
        return self._init_admin_role_use_cases().get_update_role_permissions_use_case()

    def get_delete_role_use_case(self) -> DeleteRoleUseCase:
        """Return fully configured ``DeleteRoleUseCase``."""
        return self._init_admin_role_use_cases().get_delete_role_use_case()

    def get_list_roles_use_case(self) -> ListRolesUseCase:
        """Return fully configured ``ListRolesUseCase``."""
        return self._init_admin_role_use_cases().get_list_roles_use_case()

    def get_get_role_use_case(self) -> GetRoleUseCase:
        """Return fully configured ``GetRoleUseCase``."""
        return self._init_admin_role_use_cases().get_get_role_use_case()

    # User management use cases
    def get_create_user_use_case(self) -> CreateUserUseCase:
        """Return fully configured ``CreateUserUseCase``."""
        return self._init_admin_user_use_cases().get_create_user_use_case()

    def get_update_user_roles_use_case(self) -> UpdateUserRolesUseCase:
        """Return fully configured ``UpdateUserRolesUseCase``."""
        return self._init_admin_user_use_cases().get_update_user_roles_use_case()

    def get_deactivate_user_use_case(self) -> DeactivateUserUseCase:
        """Return fully configured ``DeactivateUserUseCase``."""
        return self._init_admin_user_use_cases().get_deactivate_user_use_case()

    def get_confirm_user_email_use_case(self) -> ConfirmUserEmailUseCase:
        """Return fully configured ``ConfirmUserEmailUseCase``."""
        return self._init_admin_user_use_cases().get_confirm_user_email_use_case()

    def get_activate_user_use_case(self) -> ActivateUserUseCase:
        """Return fully configured ``ActivateUserUseCase``."""
        return self._init_admin_user_use_cases().get_activate_user_use_case()

    def get_list_users_use_case(self) -> ListUsersUseCase:
        """Return fully configured ``ListUsersUseCase``."""
        return self._init_admin_user_use_cases().get_list_users_use_case()

    def get_get_user_use_case(self) -> GetUserUseCase:
        """Return fully configured ``GetUserUseCase``."""
        return self._init_admin_user_use_cases().get_get_user_use_case()

    def get_delete_user_use_case(self) -> DeleteUserUseCase:
        """Return fully configured ``DeleteUserUseCase``."""
        return self._init_admin_user_use_cases().get_delete_user_use_case()

    # Authentication use cases
    def get_change_password_use_case(self) -> ChangePasswordUseCase:
        """Return fully configured ``ChangePasswordUseCase``."""
        return self._init_auth_use_cases().get_change_password_use_case()

    def get_login_use_case(self) -> LoginUseCase:
        """Return fully configured ``LoginUseCase``."""
        return self._init_auth_use_cases().get_login_use_case()

    def get_request_password_reset_use_case(self) -> RequestPasswordResetUseCase:
        """Return fully configured ``RequestPasswordResetUseCase``."""
        return self._init_auth_use_cases().get_request_password_reset_use_case()

    def get_reset_password_use_case(self) -> ResetPasswordUseCase:
        """Return fully configured ``ResetPasswordUseCase``."""
        return self._init_auth_use_cases().get_reset_password_use_case()

    def get_send_password_reset_email_use_case(self) -> SendPasswordResetEmailUseCase:
        """Return fully configured ``SendPasswordResetEmailUseCase``."""
        return self._init_auth_use_cases().get_send_password_reset_email_use_case()

    def get_register_use_case(self) -> RegisterUseCase:
        """Return fully configured ``RegisterUseCase``."""
        return self._init_auth_use_cases().get_register_use_case()

    def get_verify_email_use_case(self) -> VerifyEmailUseCase:
        """Return fully configured ``VerifyEmailUseCase``."""
        return self._init_auth_use_cases().get_verify_email_use_case()

    def get_resend_verification_use_case(self) -> ResendVerificationUseCase:
        """Return fully configured ``ResendVerificationUseCase``."""
        return self._init_auth_use_cases().get_resend_verification_use_case()

    def get_send_verification_email_use_case(self) -> SendVerificationEmailUseCase:
        """Return fully configured ``SendVerificationEmailUseCase``."""
        return self._init_auth_use_cases().get_send_verification_email_use_case()

    def get_send_account_exists_email_use_case(self) -> SendAccountExistsEmailUseCase:
        """Return fully configured ``SendAccountExistsEmailUseCase``."""
        return self._init_auth_use_cases().get_send_account_exists_email_use_case()

    def get_clean_unverified_accounts_use_case(self) -> CleanUnverifiedAccountsUseCase:
        """Return fully configured ``CleanUnverifiedAccountsUseCase``."""
        return self._init_auth_use_cases().get_clean_unverified_accounts_use_case()

    # Additional use cases
    def get_user_activity_stats_use_case(self) -> GetUserActivityStatsUseCase:
        """Return fully configured ``GetUserActivityStatsUseCase``."""
        return self._init_stats_use_cases().get_user_activity_stats_use_case()

    def get_service_health_use_case(self) -> GetServiceHealthUseCase:
        """Return fully configured ``GetServiceHealthUseCase``."""
        return self._init_health_use_cases().get_service_health_use_case()

    def get_read_journal_use_case(self) -> ReadJournalUseCase:
        """Return fully configured ``ReadJournalUseCase``."""
        return self._init_journal_use_cases().get_read_journal_use_case()

    def get_get_user_links_use_case(self) -> GetUserLinksUseCase:
        """Return fully configured ``GetUserLinksUseCase``."""
        return self._init_link_use_cases().get_get_user_links_use_case()

    # ------------------------------------------------------------------
    # Public service accessors
    # ------------------------------------------------------------------
    def get_link_service(self) -> LinkService:
        """Return the application facade for link operations."""
        return self._link_service

    def get_admin_service(self) -> AdminService:
        """Return the application facade for admin operations."""
        return self._admin_service

    def get_user_management_service(self) -> UserManagementService:
        """Return the service for user CRUD operations."""
        return self._user_management_service

    # ------------------------------------------------------------------
    # Public infrastructure accessors
    # ------------------------------------------------------------------
    def get_uow_factory(self) -> UnitOfWorkFactory:
        """
        Return a callable that creates fresh ``UnitOfWork`` instances.

        Returns:
            A factory with signature ``(read_only: bool = False) -> UnitOfWork``.
        """
        return self._uow_factory

    def get_logger(self, module_name: str) -> Logger:
        """
        Return a logger scoped to the given module name.

        Args:
            module_name: Typically ``__name__`` of the calling module.

        Returns:
            A ``Logger`` instance with bound module context.
        """
        return self.logger_component.get_logger(module_name)

    def get_active_logger_name(self) -> str:
        """Return the name of the currently active logger implementation."""
        return self.logger_component.get_active_logger_name()

    def get_audit_logger(self) -> AuditLogger:
        """Return the audit logger (possibly with failover)."""
        return self.audit_component.get_audit_logger()

    def get_db_manager(self) -> DatabaseManager:
        """Return the database manager (singleton)."""
        return self.db_component.get_db_manager()

    def get_cache(self) -> ServiceCache:
        """
        Return the cache in the ``ServiceCache`` combination: ``LinkCache``,
        ``RedirectCache``, ``StatsCache`` and ``CacheHealth``.
        """
        return self.cache_component.get_cache()

    def get_rate_limiter(self) -> RateLimiter:
        """Return the configured rate limiter."""
        return self.rate_limiter_component.get_rate_limiter()

    def get_task_queue(self) -> TaskQueue:
        """Return the task queue implementation (Celery or null)."""
        return self.task_queue_component.get_task_queue()

    def get_mailer(self) -> Mailer:
        """Return the mailer implementation (SMTP or null)."""
        return self.mail_component.get_mailer()

    def get_authentication_service(self) -> JwtAuthenticationService:
        """Return the JWT authentication service."""
        return self.auth_component.get_authentication_service()

    def get_authorization_service(self) -> RBACAuthorizationService:
        """Return the RBAC authorization service."""
        return self.auth_component.get_authorization_service()

    # ------------------------------------------------------------------
    # Resource cleanup
    # ------------------------------------------------------------------
    def close(self) -> None:
        """
        Release all resources held by the container.

        Closes database connections, cache connections, and shuts down
        logger/audit failover background threads.
        """
        self.db_component.close()
        self.cache_component.close()
        self.logger_component.shutdown()
        self.audit_component.shutdown()
