# Link Shortener

Сервис сокращения ссылок на Python/Flask с архитектурой Clean Architecture. Поддерживает гостевое создание ссылок, аккаунты пользователей, RBAC, асинхронную статистику и кэширование в Redis.

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-241%20passed-brightgreen.svg)]()
[![Coverage](https://img.shields.io/badge/coverage-72%25-blue.svg)]()

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

Тесты: 241 (unit + integration), покрытие: 72%

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

## CLI-команды

```bash
# Управление ссылками
flask link create --url <url>           # Создать короткую ссылку
flask link info <code>                  # Информация о ссылке
flask link list --limit N               # Последние N ссылок
flask link delete <code>                # Удалить ссылку

# Управление пользователями
flask create-admin --email <e> --password <p>  # Создать администратора
flask create-user --email <e> --password <p> --role <role>  # Создать пользователя

# Безопасность
flask security check-secrets            # Проверить настройку секретов
flask security generate-secrets         # Сгенерировать новые секреты
flask security list-users               # Список пользователей
flask security list-roles               # Список ролей
flask security validate-token <token>   # Проверить JWT токен
flask security reset-password           # Сбросить пароль

# База данных
flask db check / flask db status        # Проверить соединение с БД
flask db migrate                        # Применить миграции Alembic
flask db load-base-roles                # Загрузить системные роли
flask db seed --count N                 # Заполнить тестовыми данными

# Alembic миграции
flask alembic status                    # Текущая ревизия
flask alembic history                   # История миграций
flask alembic upgrade [revision]        # Применить миграции
flask alembic downgrade [revision]      # Откатить миграции
flask alembic migrate <message>         # Создать новую миграцию

# Статистика и обслуживание
flask stats show                        # Показать статистику
flask maintenance health                # Проверка здоровья (БД + Redis)
flask cache clear                       # Очистить кэш
```

Подробнее: [docs/OPERATIONS_AND_MIGRATIONS.md](docs/OPERATIONS_AND_MIGRATIONS.md)

## Конфигурация

Ключевые настройки в `.env`:

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `GUEST_LINK_LIMIT` | 10 | Макс. ссылок для гостя за окно |
| `GUEST_LINK_WINDOW_DAYS` | 1 | Окно подсчёта (дни) |
| `DEFAULT_GUEST_TTL_SECONDS` | 604800 | Время жизни гостевых ссылок (7 дней) |
| `CACHE_LINK_TTL` | 20 | TTL кэша (секунды) |
| `COOKIE_SECURE` | false | Secure-флаг для cookie (true в production) |

## Документация

- [Быстрый старт](docs/QUICKSTART.md) — пошаговая инструкция первого запуска
- [Руководство разработчика](docs/DEVELOPER_GUIDE.md) — архитектура, паттерны, как вносить изменения
- [Архитектура](docs/ARCHITECTURE.md) — подробное описание системы
- [Эксплуатация](docs/OPERATIONS_AND_MIGRATIONS.md) — CLI команды, миграции, обслуживание

## Лицензия

MIT
