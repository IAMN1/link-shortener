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
- Нет link preview / OG-тегов
- Нет версионирования API выше v1
- Нагрузочный профиль не снимался: пулы соединений и таймауты выставлены по
  рассуждению, а не по замеру
- Нет CI — зелёный прогон держится на том, что его кто-то запускает вручную
- `infrastructure/failover/failover_service.py` покрыт на 54%, заметно хуже
  остальной инфраструктуры. Это компонент, который работает, когда
  остальное уже сломалось

## Открытые решения

Найдено при аудите, воспроизведено, но **не изменено**: каждое меняет
поведение так, что решать должен владелец проекта. Записано здесь, чтобы не
всплыло через полгода как новость.

**Путь к SQLite относителен рабочему каталогу.** `flask` из подкаталога
создаёт *другую* базу — проверено, запуск из `src/` породил
`src/db_shortener.db`, пустой. При документированном запуске из корня
проблемы нет. Правка (разрешать относительный путь от корня проекта)
безопасна для правильного использования, но меняет то, где ищется файл БД.

**Две реализации `AuditLogger` расходятся в приоритете полей.**
`StandardAuditLogger` даёт победить полю вызова (`{**bound, **call}`),
`StructlogAuditLogger` — связанному. Failover переключает реализацию сам,
без чьего-либо участия, так что для имени поля, использованного и там и там,
содержимое аудит-журнала зависит от того, какая реализация сейчас активна.
Оба правила зафиксированы тестами в
`tests/unit/infrastructure/test_logging/test_audit_handlers.py`; какое из
них верное — не решено.

**`mask_url` не маскирует учётные данные.** Вопреки названию и docstring'ам
аудит-логгеров, функция только укорачивает URL длиннее 100 символов. Адрес
с `user:pass@` или токеном в query, если он короче, попадает в аудит-журнал
целиком — а секреты обычно короткие. Поведение зафиксировано тестом
`test_credentials_in_a_short_url_are_not_removed`.

**PostgreSQL публикуется на `0.0.0.0`.** Оба Redis намеренно привязаны к
петле — записи кэша ничем не защищены от того, кто может в них писать. Те же
соображения применимы и к БД, которая хранит вообще всё, но менять привязку
без решения владельца нельзя: это может отрезать существующие подключения.

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
# --ignore нужен, иначе соберётся и уровень 2b, требующий Docker
uv run pytest tests/integration/ --ignore=tests/integration/docker/ -v

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

Тесты: 1229 (unit + integration + e2e), покрытие: 88%

### Структура тестов

```
tests/
├── unit/                          # Моки, изолированно
│   ├── domain/                    # Сущности, value objects, политики
│   ├── application/               # Use cases, services, порты
│   ├── infrastructure/            # Config, cache, task queue
│   │   ├── test_auth/             # JWT: обязательные claim'ы, контракт authenticate()
│   │   └── test_logging/          # Форматтеры, адаптеры логгеров и аудита
│   └── web/                       # Controllers, middleware, security, schemas
│
├── integration/                   # Реальная in-memory SQLite
│   ├── application/               # Кэш против БД, удаление, кастомные коды
│   ├── infrastructure/database/   # Repository CRUD, UoW, миграции
│   ├── web/controllers/           # API, Auth, Admin
│   ├── web/middleware/            # Authentication, CSRF
│   ├── web/test_templates/        # Шаблоны против маршрутов
│   ├── cli/                       # CLI команды
│   └── docker/                    # Реальный PostgreSQL + Redis (Docker)
│
├── e2e/                           # Полные пользовательские сценарии
└── live/                          # Smoke test всех эндпоинтов
```

> **Docker-тесты не пропускаются молча.** Недоступный демон Docker — это
> законный пропуск: машина не может их выполнить. Всё остальное — отказ.
> Различие появилось не сразу: однажды тестовый стек не поднялся из-за
> занятого порта, все ветки отчитались `skipped`, и прогон вернулся зелёным
> — `492 passed, 16 skipped` вместо прежних `508 passed`. Заметил это
> только подсчёт.

> **Миграции проверяются отдельно.** `integration/infrastructure/database/
> test_migrations.py` прогоняет цепочку ревизий на настоящем файле БД.
> Остальные тесты строят схему через `create_all` из моделей и ревизий не
> исполняют — из-за чего сломанная миграция долго оставалась незамеченной.

## Ключевые файлы

| Файл | Назначение |
|------|------------|
| `web/app_factory.py` | Фабрика приложения Flask, связывает всё вместе |
| `infrastructure/di/container.py` | DI-контейнер, lazy-создание всех компонентов |
| `infrastructure/di/components/` | Компоненты DI (cache, database, auth, use_cases) |
| `infrastructure/database/role_loader.py` | Загрузка RBAC из YAML в базу данных |
| `infrastructure/configs/app/base.py` | Все константы конфигурации с переопределением через env |
| `infrastructure/configs/app/env.py` | Дескрипторы ленивого чтения env (`env_str`, `env_int`, ...) |
| `infrastructure/configs/app/factory.py` | Выбор профиля и загрузка `.env`-файлов |
| `migrations/versions/0001_initial_schema.py` | Baseline-миграция: вся схема с нуля |
| `web/controllers/api_controller.py` | REST API эндпоинты |
| `web/controllers/auth_controller.py` | Auth эндпоинты (login, register, refresh, logout) |
| `web/controllers/admin_api_controller.py` | Admin API эндпоинты |
| `web/controllers/dashboard_controller.py` | HTML-страницы панели управления |
| `domain/entities/link.py` | Основная сущность Link с бизнес-правилами |
| `web/middleware/rate_limit.py` | Rate limiting middleware |
| `web/middleware/authentication.py` | Разбор токена (заголовок или cookie), загрузка `g.current_user` |
| `web/middleware/csrf.py` | CSRF-защита cookie-сессий (double-submit) |

## Жизненный цикл гостевой ссылки

1. Гость отправляет POST на `/api/v1/shorten` с URL
2. `CreateShortLinkUseCase` проверяет лимит гостя (`GUEST_LINK_LIMIT` за `GUEST_LINK_WINDOW_DAYS`)
3. Если в пределах лимита, создаёт ссылку с `expires_at = now + DEFAULT_GUEST_TTL_SECONDS`.
   Это потолок, а не только значение по умолчанию: гость, приславший
   больший `ttl_seconds`, получит ровно `DEFAULT_GUEST_TTL_SECONDS`
4. Идентификатор гостя (IP-адрес) сохраняется для rate limiting
5. Ссылка кэшируется в Redis (L1 + L2)
6. После `expires_at` ссылка возвращает ошибку при редиректе

## Конфигурация

### Профили и .env

`FLASK_ENV` выбирает профиль — класс конфигурации из
`infrastructure/configs/app/`: `development`, `staging`, `production`,
`testing`. Профиль задаёт умолчания, `.env` их переопределяет.

Приоритет, побеждает верхний:

1. настоящая переменная окружения;
2. `.env.<профиль>`;
3. `.env`;
4. умолчание профиля в коде.

Профиль `testing` не читает `.env` — см. `ConfigFactory.NO_DOTENV_ENVS`.

### Как объявляются значения

Поля конфигурации объявляются через хелперы из
`infrastructure/configs/app/env.py`, а не через `os.environ.get()` напрямую:

```python
class BaseConfig:
    GUEST_LINK_LIMIT: int = env_int("GUEST_LINK_LIMIT", 10)
    CORS_ORIGINS: list = env_list("CORS_ORIGINS", ["http://localhost:5000"])
    REDIS_ENABLED: bool = env_bool("REDIS_ENABLED", False)
```

Хелперы возвращают дескриптор, который читает окружение **в момент обращения**
к атрибуту. Прямой вызов `os.environ.get()` в теле класса выполняется при
импорте модуля — то есть до того, как фабрика успевает загрузить `.env`,
и значение из файла молча теряется.

Внутри тел методов и `@property` можно использовать `os.environ.get()`
как обычно: они и так вычисляются лениво.

Доступные хелперы: `env_str`, `env_int`, `env_float`, `env_bool`, `env_list`
(последний разбирает строку через запятую).

Подклассы могут перекрывать поле обычным литералом — например
`TestingConfig.SECRET_KEY = "test-secret-key"`. Обычный атрибут перекрывает
дескриптор, и значение перестаёт зависеть от окружения; для тестов это нужное
поведение.

### Ключевые настройки

Полный список — в `.env.example`.

| Настройка | По умолчанию | Описание |
|-----------|--------------|----------|
| `GUEST_LINK_LIMIT` | 10 | Макс. гостевых ссылок за окно |
| `GUEST_LINK_WINDOW_DAYS` | 1 | Окно rate limit |
| `DEFAULT_GUEST_TTL_SECONDS` | 604800 | Время жизни гостевых ссылок (7 дней) — и значение по умолчанию, и потолок |
| `MAX_TTL_SECONDS` | 315360000 | Максимальный срок жизни ссылки для любого вызывающего (10 лет) |
| `MAX_URL_LENGTH` | 2048 | Максимальная длина исходного URL; выше не поднять — ширина колонки |
| `ALLOW_INTERNAL_TARGETS` | false | Разрешить ссылки внутрь собственной сети (петля, приватные диапазоны, метаданные облака) |
| `CACHE_LINK_TTL` | 3600 (20 в development) | TTL кэша ссылок (секунды) |
| `CACHE_STATS_TTL` | 300 (20 в development) | TTL кэша статистики (секунды) |
| `COOKIE_SECURE` | false | Secure-флаг для cookie (true в production) |
| `TRUSTED_PROXIES` | (пусто) | Список доверенных прокси через запятую |
| `CORS_ORIGINS` | http://localhost:5000 | Разрешённые origins для CORS |
| `SQLALCHEMY_ECHO` | false | Логирование SQL-запросов (true только для dev) |

### Безопасность

- JWT токены содержат `type` claim ("access"/"refresh") для предотвращения abuse
- Авторизация только через `Authorization: Bearer <token>` header
- `X-Forwarded-For` читается, только если запрос пришёл с адреса из
  `TRUSTED_PROXIES`, и берётся **крайний правый** элемент — тот, который
  дописал сам прокси и который клиент подделать не может. Значение обязано
  быть IP-адресом, иначе берётся адрес соединения
- Сокращать ссылки внутрь собственной сети нельзя: блок-лист приватных,
  loopback и link-local диапазонов применяется к **числовому значению
  присланного написания**, а не к его буквальной форме, поэтому
  `0177.0.0.1`, `127.1`, `2130706433` и `１２７．０．０．１` распознаются как
  петля. Юзеринфо в URL запрещено: `http://good.example@evil.example/`
  показывает жертве один домен, а ведёт на другой

  > **Чего эта проверка не делает.** DNS не разрешается — ни здесь, ни
  > позже. Имя, которое резолвится во внутренний адрес, проходит:
  > `http://127.0.0.1.nip.io/` принимается (проверено, `201 Created`).
  > Закрыть это разбором имени нельзя в принципе — запись DNS меняется
  > после проверки, — и настоящая защита от этого лежит на сетевом уровне,
  > а не в приложении. Формулировка «адрес, который получит резолвер»
  > стояла здесь раньше и обещала больше, чем есть; докстринг
  > `OriginalUrl` был точен всегда
- CORS ограничен `CORS_ORIGINS` (по умолчанию только localhost)
- `.env` файл не попадает в Docker image (секреты передаются через runtime env vars)

## Документация API

- `GET /api/openapi.json` — документ OpenAPI 3.0. Тела запросов и ответов
  генерируются из тех же pydantic-моделей, по которым валидируют эндпоинты.
  Направьте на него Swagger UI, Redoc, Postman или генератор клиента.
- `GET /api/docs` — тот же документ страницей. Просмотрщик не встраивается:
  это полтора мегабайта чужих ассетов или тег `script` на чужой CDN.

Тест `tests/integration/web/controllers/test_api_docs.py` сверяет документ с
настоящей картой маршрутов, поэтому новый эндпоинт — это падающий тест, а не
незадокументированный эндпоинт.

## Удаление гостевой ссылки

У ссылки, созданной без учётной записи, нет владельца, поэтому `link:delete_own`
для неё не срабатывает никогда. Ответ на создание несёт `deletion_token` —
подписанный идентификатор строки, выдаётся единожды. Удалить такую ссылку
можно, передав его в заголовке:

```bash
curl -X DELETE http://localhost:5000/api/v1/links/<code> \
  -H "X-Deletion-Token: <token>"
```

Токен называет конкретную строку, а не код: код освобождается при удалении и
может быть выдан снова.

## CLI-команды

```bash
# Ссылки
flask link create --url <url>
flask link create --url <url> --code <code>   # 6-10 of A-Z a-z 0-9 _ -
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

См. `.env.example` — шаблон со всеми переменными и описаниями. Он единственный env-файл в репозитории; `.env` и `.env.docker` создаются локально и в git не попадают.
