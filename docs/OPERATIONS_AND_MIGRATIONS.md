# Эксплуатация и миграции

Миграции базы данных, CLI-команды и процедуры обслуживания.

## Миграции базы данных (Alembic)

### Применение миграций

```bash
docker compose run --rm migrations alembic upgrade head
```

### Создание новой миграции

```bash
docker compose run --rm migrations alembic revision --autogenerate -m "описание"
```

### Откат

```bash
docker compose run --rm migrations alembic downgrade -1
```

## CLI-команды

Все команды выполняются внутри контейнера `app`:

```bash
docker compose exec app flask <команда>
```

### Управление пользователями

| Команда | Описание |
|---------|----------|
| `flask create-admin --email <email> --password <pwd>` | Создать администратора |
| `flask create-user --email <email> --password <pwd> --role <role>` | Создать пользователя с указанной ролью |

### Безопасность

| Команда | Описание |
|---------|----------|
| `flask security check-secrets` | Проверить настройку секретов |
| `flask security generate-secrets` | Сгенерировать новые SECRET_KEY и SHORT_CODE_PEPPER |
| `flask security list-users` | Показать список всех пользователей |
| `flask security list-roles` | Показать список ролей и разрешений |
| `flask security validate-token <token>` | Проверить JWT токен и показать claims |
| `flask security reset-password` | Сбросить пароль пользователя |

### База данных

| Команда | Описание |
|---------|----------|
| `flask db check` / `flask db status` | Проверить соединение с БД |
| `flask db init` | Создать таблицы (только если USE_ALEMBIC=false) |
| `flask db drop --yes` | Удалить все таблицы (ОПАСНО) |
| `flask db migrate` | Применить миграции Alembic |
| `flask db load-base-roles` | Загрузить/обновить системные роли из YAML |
| `flask db load-custom-roles <file>` | Загрузить роли из YAML файла |
| `flask db seed --count N` | Заполнить БД тестовыми ссылками |

### Alembic миграции

| Команда | Описание |
|---------|----------|
| `flask alembic status` | Показать текущую ревизию |
| `flask alembic history` | Показать историю миграций |
| `flask alembic upgrade [revision]` | Применить миграции (по умолчанию: head) |
| `flask alembic downgrade [revision]` | Откатить миграции (по умолчанию: -1) |
| `flask alembic migrate <message>` | Создать новую миграцию с автогенерацией |

### Статистика

| Команда | Описание |
|---------|----------|
| `flask stats show` | Показать статистику сервиса |
| `flask stats refresh` | Обновить кэш статистики |

### Кэш

| Команда | Описание |
|---------|----------|
| `flask cache clear` | Полностью очистить кэш |
| `flask cache clear --stats-only` | Очистить только кэш статистики |
| `flask cache stats` | Показать информацию о кэше |

### Обслуживание

| Команда | Описание |
|---------|----------|
| `flask maintenance health` | Проверка здоровья (БД + Redis) |
| `flask maintenance clean-expired --days N` | Удалить ссылки, не использовавшиеся N дней |
| `flask maintenance check-redis` | Проверить соединение с Redis |

### Управление ссылками

| Команда | Описание |
|---------|----------|
| `flask link create --url <url>` | Создать короткую ссылку |
| `flask link info <code>` | Показать информацию о ссылке |
| `flask link delete <code>` | Удалить ссылку |
| `flask link list --limit N` | Показать последние N ссылок |

## Справочник конфигурации

Все настройки в `.env` с переопределением через переменные окружения.

### Настройки гостевых ссылок

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `GUEST_LINK_LIMIT` | 10 | Макс. ссылок для гостя за окно |
| `GUEST_LINK_WINDOW_DAYS` | 1 | Окно подсчёта (дни) |
| `DEFAULT_GUEST_TTL_SECONDS` | 604800 | Время жизни гостевых ссылок (7 дней) |

### Безопасность

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `SECRET_KEY` | dev-ключ | Секрет Flask (менять в продакшене) |
| `SHORT_CODE_PEPPER` | dev-pepper | Перец для хеширования коротких кодов |
| `COOKIE_SECURE` | false | Secure-флаг для cookie (true в production) |
| `SESSION_COOKIE_SECURE` | false | Secure-флаг для сессионных cookie (true в ProductionConfig) |
| `SESSION_COOKIE_SAMESITE` | Lax | SameSite policy для cookie |
| `SESSION_COOKIE_HTTPONLY` | true | HttpOnly-флаг для cookie |

### Rate Limiting

| Эндпоинт | Лимит | Период | Описание |
|----------|-------|--------|----------|
| `auth.login` | 5 | 60 сек | Защита от brute-force |
| `auth.register` | 3 | 3600 сек | Защита от спама |
| `auth.refresh_token` | 10 | 60 сек | Защита от replay |
| `auth.logout` | 20 | 60 сек | |
| `api.create_short_link` | 30 | 60 сек | По умолчанию |
| `api.batch_create` | 5 | 60 сек | Пакетное создание |
| `redirect_to_original` | 200 | 60 сек | Редиректы |

Настройки в `infrastructure/configs/app/base.py` → `RATE_LIMITS`.

### База данных

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `DATABASE_TYPE` | postgresql | Тип СУБД |
| `DATABASE_HOST` | localhost | Хост БД |
| `DATABASE_PORT` | 5432 | Порт БД |
| `DATABASE_NAME` | db_shortener | Имя базы данных |
| `DATABASE_USER` | db_user | Пользователь БД |
| `DATABASE_PASSWORD` | db_password | Пароль БД |
| `DATABASE_POOL_SIZE` | 20 | Размер пула соединений |

### Redis / Кэш

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `REDIS_ENABLED` | true | Использовать Redis для кэша |
| `CACHE_LINK_TTL` | 20 | TTL кэша ссылок (секунды) |
| `CACHE_STATS_TTL` | 20 | TTL кэша статистики (секунды) |

### Celery

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `CELERY_ENABLED` | true | Включить асинхронные задачи |
| `CELERY_BROKER_URL` | URL Redis | Брокер сообщений |

## Расписание обслуживания

Рекомендуемые cron-задачи:

- **Ежедневно**: `flask maintenance clean-expired` — удаление истёкших гостевых ссылок
- **Еженедельно**: `flask stats refresh` — обновление кэша статистики
- **Ежемесячно**: `flask maintenance clean-expired --days 90` — удаление неиспользуемых ссылок

## Резервное копирование

```bash
docker compose exec db pg_dump -U db_user db_shortener > backup.sql
```

## Проверка здоровья

API эндпоинт: `GET /api/v1/admin/health` (требует роль admin)

Ответ:
```json
{
  "database": true,
  "cache": true,
  "task_queue": true
}
```

> **Примечание:** результаты проверки здоровья кэшируются 15 секунд для снижения нагрузки на инфраструктуру.

Docker healthcheck: `GET /health` (проверяется автоматически каждые 30 секунд)

## Тестирование

### Запуск тестов

```bash
# Все тесты (Docker-сервисы поднимаются автоматически)
uv run pytest tests/ -v

# Только unit-тесты
uv run pytest tests/unit/ -v

# Только интеграционные (SQLite)
uv run pytest tests/integration/ --ignore=tests/integration/docker/ -v

# Docker-интеграционные (PostgreSQL + Redis — поднимаются автоматически)
uv run pytest tests/integration/docker/ -v

# E2E тесты
uv run pytest tests/e2e/ -v

# Smoke test всех эндпоинтов
uv run python tests/live/smoke_test.py

# С покрытием
uv run pytest tests/ --cov=src/link_shortener --cov-report=term-missing
```

### Управление Docker-сервисами для тестов

```bash
# Запустить тестовые сервисы (PostgreSQL + Redis)
docker compose -f docker-compose.test.yml up -d

# Проверить статус
docker compose -f docker-compose.test.yml ps

# Остановить и удалить данные
docker compose -f docker-compose.test.yml down -v
```

> **Примечание:** при запуске `pytest tests/integration/docker/` Docker-сервисы поднимаются и останавливаются автоматически.

## Обновление приложения

```bash
git pull
docker compose build --no-cache
docker compose run --rm migrations alembic upgrade head
docker compose up -d
```
