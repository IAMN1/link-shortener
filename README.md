# Link Shortener

Сервис сокращения ссылок на Python/Flask с архитектурой Clean Architecture. Поддерживает гостевое создание ссылок, аккаунты пользователей, RBAC, асинхронную статистику и кэширование в Redis.

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-224%20passed-brightgreen.svg)]()
[![Coverage](https://img.shields.io/badge/coverage-71%25-blue.svg)]()

## Возможности

- **Гостевые ссылки** — сокращение URL без регистрации (автоистечение через 7 дней)
- **Аккаунты пользователей** — постоянные ссылки, личная статистика, панель управления
- **Пакетное создание** — сокращение нескольких URL за один запрос
- **TTL** — настраиваемое время жизни ссылок (гости: 7 дней по умолчанию, пользователи: любое)
- **RBAC** — четыре роли: guest, user, analyst, admin
- **Кэширование** — двухуровневый кэш (L1: редиректы, L2: объекты ссылок) с инвалидацией при удалении
- **Асинхронная статистика** — подсчёт кликов через Celery
- **Rate limiting** — защита от brute-force на auth-эндпоинтах
- **Health check кэширование** — результаты проверки здоровья кэшируются 15 сек
- **CLI** — команды обслуживания для администраторов

## Быстрый старт

```bash
git clone https://github.com/your-org/link-shortener.git
cd link-shortener
# Отредактируйте .env (задайте SECRET_KEY, DATABASE_PASSWORD, REDIS_PASSWORD)
docker compose build --no-cache
docker compose run --rm migrations alembic upgrade head
docker compose up -d
docker compose exec app flask create-admin --email admin@example.com --password secret
```

Откройте `http://localhost:5000/` — можно сокращать ссылки сразу без регистрации.

Подробнее: [docs/QUICKSTART.md](docs/QUICKSTART.md)

## API

| Метод | Эндпоинт | Авторизация | Описание |
|-------|----------|-------------|----------|
| POST | `/api/v1/shorten` | Нет | Создать короткую ссылку (гость или пользователь) |
| GET | `/api/v1/links/<code>` | Нет | Информация о ссылке |
| GET | `/api/v1/links/<code>/extended` | Нет | Расширенная аналитика |
| GET | `/api/v1/links/mine` | Да | Список ссылок пользователя (пагинация: `offset`, `limit`) |
| DELETE | `/api/v1/links/<code>` | Да | Удалить ссылку |
| GET | `/api/v1/stats/mine` | Да | Личная статистика |
| POST | `/api/v1/batch/shorten` | Нет | Пакетное создание ссылок |
| POST | `/api/v1/auth/register` | Нет | Регистрация |
| POST | `/api/v1/auth/login` | Нет | Получить JWT токены |
| POST | `/api/v1/auth/refresh` | Cookie | Обновить access token |
| POST | `/api/v1/auth/logout` | Cookie | Выход |
| GET | `/api/v1/admin/health` | Admin | Проверка здоровья инфраструктуры |
| GET | `/api/v1/admin/users` | Admin | Список пользователей |
| GET | `/api/v1/admin/roles` | Admin | Список ролей |

### Rate Limiting

| Эндпоинт | Лимит | Описание |
|----------|-------|----------|
| `POST /api/v1/auth/login` | 5 / мин | Защита от brute-force |
| `POST /api/v1/auth/register` | 3 / час | Защита от спама |
| `POST /api/v1/auth/refresh` | 10 / мин | Защита от replay |
| `POST /api/v1/auth/logout` | 20 / мин | |
| `POST /api/v1/shorten` | 30 / мин | По умолчанию |

### Пагинация

`GET /api/v1/links/mine` поддерживает query-параметры:
- `offset` — количество пропущенных записей (по умолчанию 0)
- `limit` — максимальное количество записей (по умолчанию 50, макс. 200)

## Архитектура

```
src/link_shortener/
├── domain/          # Сущности, объекты-значения, интерфейсы репозиториев
├── application/     # Use case'ы, DTO, сервисы приложения, порты
├── infrastructure/  # Реализации: БД, кэш, авторизация, DI, CLI
└── web/             # Контроллеры, middleware, шаблоны, статика
```

Подробнее: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## Тестирование

Менеджер пакетов: **uv**

```bash
# Все тесты
uv run pytest tests/ -v

# Только unit-тесты
uv run pytest tests/unit/ -v

# Только интеграционные тесты
uv run pytest tests/integration/ -v

# С покрытием
uv run pytest tests/ --cov=src/link_shortener --cov-report=term-missing
```

Тесты: 224 (unit + integration), покрытие: 71%

## Технологический стек

| Компонент | Технология |
|-----------|------------|
| Язык | Python 3.12 |
| Фреймворк | Flask 3.x |
| База данных | PostgreSQL 15 |
| Кэш | Redis 7 |
| Задачи | Celery 5.x |
| Миграции | Alembic |
| Авторизация | JWT (PyJWT) |
| Валидация | Pydantic v2 |
| Логирование | structlog |
| Менеджер пакетов | uv |
| Контейнеризация | Docker, Docker Compose |

## Конфигурация

Ключевые настройки в `.env`:

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `GUEST_LINK_LIMIT` | 10 | Макс. ссылок для гостя за окно |
| `GUEST_LINK_WINDOW_DAYS` | 1 | Окно подсчёта (дни) |
| `DEFAULT_GUEST_TTL_SECONDS` | 604800 | Время жизни гостевых ссылок (7 дней) |
| `CACHE_LINK_TTL` | 20 | TTL кэша (секунды) |
| `COOKIE_SECURE` | false | Secure-флаг для cookie (true в production) |

Полный список: [docs/OPERATIONS_AND_MIGRATIONS.md](docs/OPERATIONS_AND_MIGRATIONS.md)

## Документация

- [Быстрый старт](docs/QUICKSTART.md) — пошаговая инструкция первого запуска
- [Руководство разработчика](docs/DEVELOPER_GUIDE.md) — архитектура, паттерны, как вносить изменения
- [Архитектура](docs/ARCHITECTURE.md) — подробное описание системы
- [Эксплуатация](docs/OPERATIONS_AND_MIGRATIONS.md) — CLI команды, миграции, обслуживание

## Лицензия

MIT
