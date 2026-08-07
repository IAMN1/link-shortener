# Быстрый старт

Пошаговая инструкция по запуску сервиса с нуля.

Есть два сценария запуска, они независимы:

| Сценарий | Что нужно | Для чего |
|----------|-----------|----------|
| **A. Локально** | Python 3.12 + [uv](https://docs.astral.sh/uv/) | Разработка и отладка. SQLite, кэш в памяти, без Celery |
| **B. В Docker** | Docker и Docker Compose v2+ | Полный стек: PostgreSQL, Redis, Celery |

## Как устроена конфигурация

Прежде чем запускать, важно понять две вещи.

**`FLASK_ENV` выбирает профиль** — класс конфигурации из
`infrastructure/configs/app/`: `development`, `staging`, `production`,
`testing`. Профиль задаёт умолчания для своего окружения.

**`.env` переопределяет умолчания профиля.** Приоритет, побеждает верхний:

1. настоящая переменная окружения (`export VAR=...`, `environment:` в compose);
2. `.env.<профиль>` — например `.env.production`;
3. `.env`;
4. умолчание профиля в коде.

То есть профиль и `.env` не конкурируют: профиль — это база, `.env` — точечные
правки поверх неё.

> Профиль `testing` намеренно **не читает** `.env`-файлы: автотесты должны
> давать одинаковый результат на любой машине.

В репозитории лежит `.env.example` — шаблон со всеми переменными и описаниями.
Файлы `.env` и `.env.docker` в git не попадают: в них секреты.

---

# Сценарий A: локальный запуск

## Шаг A1: Клонирование и зависимости

```bash
git clone https://github.com/your-org/link-shortener.git
cd link-shortener
uv sync
```

`uv sync` создаёт `.venv` и ставит сам проект в editable-режиме, поэтому
команды `flask` и `alembic` работают без `PYTHONPATH`.

## Шаг A2: Файл окружения

```bash
cp .env.example .env
```

Минимально задайте секреты (сгенерировать: `uv run flask security generate-secrets`):

```ini
SECRET_KEY=<случайная hex-строка 64 байта>
SHORT_CODE_PEPPER=<другой секретный ключ>
```

Остальное для локального запуска уже подходит: `DATABASE_TYPE=sqlite`,
`REDIS_ENABLED=false`, `CELERY_ENABLED=false`.

> Никогда не коммитьте реальные секреты в репозиторий.

## Шаг A3: Создание схемы базы данных

```bash
uv run flask alembic upgrade head
```

Применяет baseline-миграцию `0001_initial_schema` — создаёт таблицы
`users`, `roles`, `permissions`, `urls` и связующие таблицы.

## Шаг A4: Системные роли

```bash
uv run flask db load-base-roles
```

Загружает роли `guest`, `user`, `analyst`, `admin` и их разрешения из
`infrastructure/configs/rbac/roles.yaml`. Команда идемпотентна.

> Миграция создаёт только **схему**, но не данные. Роли — отдельный шаг.
> В профиле `development` они досоздаются и автоматически при старте
> (`AUTO_SEED_ROLES=true`), в `production` — нет.
>
> Поэтому в `development` эта команда обычно печатает
> `permissions created: 0; roles created: 0` — роли уже засеяны при первом
> запуске приложения. Это не холостой ход и не ошибка: команда идемпотентна
> и подтверждает, что всё на месте. Ненулевые числа увидите на базе, к
> которой приложение ещё ни разу не подключалось, и в `production`.

> **Шаг обязательный, а не косметический.** Анонимный запрос выполняется в
> роли `guest`, и именно она несёт `link:create`. Пока роли не засеяны,
> публичное сокращение ссылок отвечает `401`. Это сделано намеренно:
> отсутствие роли значит «не сказано, что можно гостю», и открывать доступ
> по умолчанию в такой ситуации нельзя.
>
> То же касается **уже развёрнутой** базы, засеянной до того, как в роль
> `guest` добавили `link:create`: команду нужно выполнить повторно, она
> идемпотентна. Проверить фактическое состояние — `flask security list-roles`.

## Шаг A5: Администратор

```bash
uv run flask create-admin --email admin@example.com --password your_password
```

## Шаг A6: Запуск

```bash
uv run flask run
```

Сервис доступен на `http://127.0.0.1:5000/`.

---

# Сценарий B: запуск в Docker

## Шаг B1: Клонирование

```bash
git clone https://github.com/your-org/link-shortener.git
cd link-shortener
```

## Шаг B2: Файл окружения

```bash
cp .env.example .env.docker
```

Задайте в нём секреты и пароли инфраструктуры:

```ini
ENV_FILE=.env.docker          # должен совпадать со значением --env-file
SECRET_KEY=<случайная hex-строка 64 байта>
SHORT_CODE_PEPPER=<другой секретный ключ>

DATABASE_TYPE=postgresql
DATABASE_HOST=db
DATABASE_NAME=db_shortener    # имя базы, а не файла: значение из шаблона
                              # (db_shortener.db) рассчитано на SQLite
DATABASE_USER=shortener
DATABASE_PASSWORD=<надёжный пароль>

REDIS_ENABLED=true
REDIS_PASSWORD=<надёжный пароль>
CELERY_ENABLED=true

DOMAIN=localhost:5000         # обязательно при HOST=0.0.0.0
```

> `DOMAIN` без значения даст короткие ссылки вида `http://0.0.0.0:5000/<код>`,
> которые не открываются в браузере.

## Шаг B3: Сборка и запуск

```bash
docker compose --env-file .env.docker up -d --build
```

Флаг `--env-file` обязателен, иначе compose возьмёт `.env`, рассчитанный на
локальный SQLite.

Это **стек для разработки**: dev-сервер Flask с отладчиком, смонтированные
исходники, порт на `127.0.0.1`. Задано это в `docker-compose.override.yml`,
который compose подхватывает автоматически — отдельного флага не нужно.

Продакшн-форма — тот же стек без надстройки:

```bash
docker compose -f docker-compose.yml --env-file .env.docker up -d --build
```

Приложение тогда запускается командой образа — gunicorn с потолком на запрос,
без отладчика и без монтирования исходников. Отличить одно от другого можно
по `/console`: в dev он отвечает `200`, в продакшн-форме `404`.

Порядок запуска задан зависимостями: `db` и `redis` поднимаются до `healthy`,
затем сервис `migrations` выполняет `alembic upgrade head` и завершается,
и только после этого стартует `app`. Отдельного шага для миграций не нужно.

Проверьте состояние:

```bash
docker compose --env-file .env.docker ps
docker compose --env-file .env.docker logs app
```

## Шаг B4: Роли и администратор

```bash
docker compose --env-file .env.docker exec app flask db load-base-roles
docker compose --env-file .env.docker exec app \
    flask create-admin --email admin@example.com --password your_password
```

Для создания обычного пользователя:

```bash
docker compose --env-file .env.docker exec app \
    flask create-user --email user@example.com --password user_password --role user
```

## Шаг B5: Проверка

```bash
curl -X POST http://localhost:5000/api/v1/shorten \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'
```

---

# Использование приложения

### Как гость (без аккаунта)

Откройте `http://localhost:5000/` и:
- Вставьте URL и нажмите **Shorten** — создастся ссылка, действительная 7 дней
- Используйте вкладку **Info** — lookup любого короткого кода
- Используйте вкладку **Extended** — расширенная аналитика по коду

### Регистрация и вход

1. Нажмите **Sign Up** в шапке или перейдите на `http://localhost:5000/register`
2. Войдите на `http://localhost:5000/login`
3. Вы попадёте на панель управления

### Примеры API

```bash
# Создание ссылки (гость)
curl -X POST http://localhost:5000/api/v1/shorten \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'

# Создание с кастомным TTL (1 час)
curl -X POST http://localhost:5000/api/v1/shorten \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "ttl_seconds": 3600}'

# Просмотр информации о ссылке (публичный)
curl http://localhost:5000/api/v1/links/<short_code>

# Просмотр расширенной информации (публичный)
curl http://localhost:5000/api/v1/links/<short_code>/extended

# Вход
curl -X POST http://localhost:5000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.com", "password": "your_password"}'

# Мои ссылки (с пагинацией)
curl http://localhost:5000/api/v1/links/mine?offset=0&limit=20 \
  -H "Authorization: Bearer <token>"

# Удаление ссылки
curl -X DELETE http://localhost:5000/api/v1/links/<short_code> \
  -H "Authorization: Bearer <token>"
```

## Разделы панели управления

| Раздел | Доступ | Описание |
|--------|--------|----------|
| Мои ссылки | `link:view_own`, `link:delete_own` | Просмотр, управление, удаление ссылок |
| Моя статистика | `link:view_own` | Личная аналитика кликов |
| Создать ссылку | `link:create` | Форма с выбором TTL |
| Статистика сервиса | `stats:view_basic`; разбивка по популярным — `stats:view_full` | Глобальная статистика |
| Пользователи | admin | Управление пользователями |
| Роли | admin | Управление ролями и разрешениями |
| Проверка здоровья | admin | Статус БД, Redis, Celery |

# Дальнейшие шаги

## Тесты

```bash
# Все тесты (Docker-сервисы для уровня 2b поднимаются автоматически)
uv run pytest tests/ -v

# Только unit-тесты
uv run pytest tests/unit/ -v

# Только интеграционные (in-memory SQLite)
uv run pytest tests/integration/ --ignore=tests/integration/docker/ -v

# E2E тесты
uv run pytest tests/e2e/ -v
```

## Celery локально (опционально)

Нужен только при `CELERY_ENABLED=true`. Требует запущенного Redis:

```bash
uv run celery -A link_shortener.infrastructure.task_queue.celery_app worker --loglevel=info
```

При `CELERY_ENABLED=false` клики считаются синхронно в обработчике редиректа —
статистика не теряется, но добавляется запрос к БД в критический путь.

## Изменение схемы базы данных

После правки моделей в `infrastructure/database/models/`:

```bash
uv run flask alembic migrate "описание изменения"   # создать ревизию
uv run flask alembic upgrade head                   # применить
```

Подробнее — [docs/OPERATIONS_AND_MIGRATIONS.md](OPERATIONS_AND_MIGRATIONS.md).

## Если что-то не работает

| Симптом | Причина и решение |
|---------|-------------------|
| `ModuleNotFoundError: No module named 'link_shortener'` | Не выполнен `uv sync`, либо команда запущена не через `uv run` |
| `no such table: urls` | Не применены миграции: `uv run flask alembic upgrade head` |
| `Role 'user' not found` при регистрации | Не загружены роли: `uv run flask db load-base-roles` |
| `401` на `POST /api/v1/shorten` у неаутентифицированного клиента | Роль `guest` несёт `link:create`, и без неё анонимное сокращение закрыто. Две причины: роли нет вовсе (в логе `Guest role is missing`) или роль засеяна раньше, чем в неё добавили `link:create` — тогда лог молчит на уровне `info`, смотреть `uv run flask security list-roles`. Лечится одинаково: `uv run flask db load-base-roles` |
| `403` на `POST /api/v1/shorten` у вошедшего пользователя | У его роли нет `link:create` — например, роль `analyst` его не имеет по замыслу. Проверить: `uv run flask security list-roles` |
| Значения из `.env` не применяются | Профиль `testing` игнорирует `.env` намеренно. В остальных случаях проверьте, что переменная не задана в окружении — она имеет приоритет над файлом |
| `No 'script_location' key found` | Команда `alembic` запущена не из корня проекта, где лежит `alembic.ini` |
| Короткие ссылки вида `http://0.0.0.0:5000/...` | Не задан `DOMAIN` при `HOST=0.0.0.0` |
| `SECRET_KEY must be set in environment` | Профили `staging` и `production` требуют явные секреты |
| JWT перестают работать после рестарта | `SECRET_KEY` не задан — в `development` он генерируется случайно при каждом запуске |
