# Руководство разработчика

Памятка для разработчиков, работающих над проектом link-shortener.

## Что за проект?

Полнофункциональный сервис сокращения ссылок на Python/Flask, построенный по принципам Clean Architecture. Поддерживает:

- **Гостевое создание ссылок** — кто угодно может сократить URL без аккаунта (ссылки истекают через 7 дней по умолчанию)
- **Аккаунты пользователей** — зарегистрированные пользователи получают постоянные ссылки, личную статистику и панель управления
- **RBAC** — контроль доступа на основе ролей с четырьмя ролями: guest, user, analyst, admin
- **Асинхронную статистику** — подсчёт кликов через Celery
- **Кэширование** — двухуровневый кэш (L1: редиректы, L2: объекты ссылок) с инвалидацией при удалении
- **Rate limiting** — защита от brute-force на auth-эндпоинтах
- **Аудит** — структурированное логирование всех значимых событий
- **Health check кэширование** — результаты проверки здоровья кэшируются 15 сек

## Текущий статус проекта

**Альфа / Разработка**. Основной функционал работает:
- Создание ссылок (поштучное и пакетное)
- Гостевой и авторизованный режимы с TTL
- Регистрация пользователей и JWT-аутентификация
- Удаление ссылок с инвалидацией кэша и логированием ошибок
- Пагинация для списка ссылок пользователя
- Админ-панель с управлением пользователями/ролями
- Rate limiting на auth-эндпоинтах
- Мониторинг здоровья сервиса с кэшированием
- CLI-команды для обслуживания

**Известные ограничения:**
- Нет HTTPS в режиме разработки
- Health check для Celery — заглушка (всегда возвращает true)
- Нет link preview / OG-тегов
- Нет версионирования API выше v1

## Архитектура

```
src/link_shortener/
├── domain/              # Сущности, объекты-значения, интерфейсы репозиториев
├── application/         # Use case'ы, DTO, сервисы приложения (фасады), порты
├── infrastructure/      # Конкретные реализации: БД, кэш, авторизация, DI, CLI
└── web/                 # Flask-контроллеры, middleware, шаблоны, статические файлы
```

**Ключевые паттерны:**
- **Repository** — абстрактные интерфейсы хранения в `domain/`, реализации SQLAlchemy в `infrastructure/`
- **Unit of Work** — управление транзакциями через контекстные менеджеры
- **Dependency Injection** — компонентный контейнер в `infrastructure/di/` с lazy-инициализацией
- **Facade** — `LinkService` и `AdminService` упрощают доступ веб-слоя к use case'ам
- **Decorator** — `@login_required` и `@require_permission` для аутентификации/авторизации
- **Failover** — логгер и кэш деградируют без ошибок (structlog → standard → null)

## Запуск тестов

Менеджер пакетов: **uv**

Проект использует три уровня тестирования:

```bash
# Уровень 1: Unit-тесты (моки, изолированно)
uv run pytest tests/unit/ -v

# Уровень 2: Интеграционные тесты (реальная in-memory SQLite)
uv run pytest tests/integration/ -v

# Уровень 2b: Интеграционные тесты (реальный PostgreSQL + Redis)
# Docker-сервисы поднимаются автоматически
uv run pytest tests/integration/docker/ -v

# Уровень 3: E2E тесты (полные пользовательские сценарии)
uv run pytest tests/e2e/ -v

# Все тесты вместе
uv run pytest tests/ -v

# С покрытием
uv run pytest tests/ --cov=src/link_shortener --cov-report=term-missing
```

Тесты: 319 (unit + integration + e2e), покрытие: 79%

### Структура тестов

```
tests/
├── unit/                          # Моки, изолированно
│   ├── domain/                    # Сущности, value objects
│   ├── application/               # Use cases, services
│   ├── infrastructure/            # Config, cache, task queue
│   └── web/                       # Controllers, middleware
│
├── integration/                   # Реальная in-memory SQLite
│   ├── infrastructure/database/   # Repository CRUD, UoW
│   ├── web/controllers/           # API, Auth, Admin
│   ├── web/middleware/            # Authentication
│   ├── cli/                       # CLI команды
│   └── docker/                    # Реальный PostgreSQL + Redis (Docker)
│
├── e2e/                           # Полные пользовательские сценарии
└── live/                          # Smoke test всех эндпоинтов
```

## Ключевые файлы

| Файл | Назначение |
|------|------------|
| `web/app_factory.py` | Фабрика приложения Flask, связывает всё вместе |
| `infrastructure/di/container.py` | DI-контейнер, lazy-создание всех компонентов |
| `infrastructure/di/components/` | Компоненты DI (cache, database, auth, use_cases) |
| `infrastructure/database/role_loader.py` | Загрузка RBAC из YAML в базу данных |
| `infrastructure/configs/app/base.py` | Все константы конфигурации с переопределением через env |
| `web/controllers/api_controller.py` | REST API эндпоинты |
| `web/controllers/auth_controller.py` | Auth эндпоинты (login, register, refresh, logout) |
| `web/controllers/admin_api_controller.py` | Admin API эндпоинты |
| `web/controllers/dashboard_controller.py` | HTML-страницы панели управления |
| `domain/entities/link.py` | Основная сущность Link с бизнес-правилами |
| `web/middleware/rate_limit.py` | Rate limiting middleware |

## Жизненный цикл гостевой ссылки

1. Гость отправляет POST на `/api/v1/shorten` с URL
2. `CreateShortLinkUseCase` проверяет лимит гостя (`GUEST_LINK_LIMIT` за `GUEST_LINK_WINDOW_DAYS`)
3. Если в пределах лимита, создаёт ссылку с `expires_at = now + DEFAULT_GUEST_TTL_SECONDS`
4. Идентификатор гостя (IP-адрес) сохраняется для rate limiting
5. Ссылка кэшируется в Redis (L1 + L2)
6. После `expires_at` ссылка возвращает ошибку при редиректе

## Конфигурация

Все настройки в `.env` или переменных окружения. См. `infrastructure/configs/app/base.py` для значений по умолчанию. Ключевые настройки:

| Настройка | По умолчанию | Описание |
|-----------|--------------|----------|
| `GUEST_LINK_LIMIT` | 10 | Макс. гостевых ссылок за окно |
| `GUEST_LINK_WINDOW_DAYS` | 1 | Окно rate limit |
| `DEFAULT_GUEST_TTL_SECONDS` | 604800 | Время жизни гостевых ссылок (7 дней) |
| `CACHE_LINK_TTL` | 20 | TTL кэша ссылок (секунды) |
| `CACHE_STATS_TTL` | 20 | TTL кэша статистики (секунды) |
| `COOKIE_SECURE` | false | Secure-флаг для cookie (true в production) |
| `TRUSTED_PROXIES` | (пусто) | Список доверенных прокси через запятую |
| `CORS_ORIGINS` | http://localhost:5000 | Разрешённые origins для CORS |
| `SQLALCHEMY_ECHO` | false | Логирование SQL-запросов (true только для dev) |

### Безопасность

- JWT токены содержат `type` claim ("access"/"refresh") для предотвращения abuse
- Авторизация только через `Authorization: Bearer <token>` header
- `X-Forwarded-For` проверяется через `TRUSTED_PROXIES` перед доверием
- CORS ограничен `CORS_ORIGINS` (по умолчанию только localhost)
- `.env` файл не попадает в Docker image (секреты注入 через runtime env vars)

## CLI-команды

```bash
# Ссылки
flask link create --url <url>
flask link info <short_code>
flask link delete <short_code>
flask link list --limit 10

# Пользователи
flask create-admin --email admin@example.com --password secret
flask create-user --email user@example.com --password user123 --role user

# Безопасность
flask security check-secrets
flask security generate-secrets
flask security list-users
flask security list-roles
flask security validate-token <jwt_token>

# База данных
flask db check
flask db status
flask db migrate
flask db load-base-roles
flask db seed --count 10

# Alembic
flask alembic status
flask alembic history
flask alembic upgrade head

# Статистика и обслуживание
flask stats show
flask maintenance health
flask cache clear
```

## Как добавить новый use case

1. Создайте `application/use_cases/<domain>/<name>.py` с `@dataclass`, наследующим `BaseUseCase`
2. Добавьте порт (интерфейс) в `application/ports/`, если нужна новая инфраструктура
3. Свяжите в `infrastructure/di/components/use_cases/`
4. Добавьте геттер в `infrastructure/di/container.py`
5. Экспортируйте через фасад-сервис или напрямую в контроллере
6. Напишите тесты в `tests/unit/application/test_use_cases/`

## Справочник переменных окружения

См. `.env` для полного списка с описаниями. Файл подробно прокомментирован.
