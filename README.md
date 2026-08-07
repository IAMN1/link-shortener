# Link Shortener

Сервис сокращения ссылок на Python/Flask с архитектурой Clean Architecture. Поддерживает гостевое создание ссылок, аккаунты пользователей, RBAC, асинхронную статистику и кэширование в Redis.

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-1229%20passed-brightgreen.svg)]()
[![Coverage](https://img.shields.io/badge/coverage-88%25-blue.svg)]()

## Возможности

- **Гостевые ссылки** — сокращение URL без регистрации (автоистечение через 7 дней)
- **Аккаунты пользователей** — постоянные ссылки, личная статистика, панель управления
- **Пакетное создание** — сокращение нескольких URL за один запрос
- **TTL** — настраиваемое время жизни ссылок (гости: 7 дней по умолчанию, пользователи: любое)
- **Дедупликация в пределах владельца** — повторное сокращение своего URL отдаёт свою же
  живую ссылку (`200`, `is_new: false`); чужая и истёкшая не отдаются никогда
- **RBAC** — четыре роли: guest, user, analyst, admin. Анонимный запрос
  выполняется в роли `guest`, а не «без ролей»; над ней стоит потолок
  разрешений, заданный в коде
- **Кэширование** — двухуровневый кэш (L1: редиректы, L2: объекты ссылок) с инвалидацией при удалении
- **Асинхронная статистика** — подсчёт кликов через Celery
- **Rate limiting** — защита от brute-force на auth-эндпоинтах
- **Health check кэширование** — результаты проверки здоровья кэшируются 15 сек
- **CLI** — команды обслуживания для администраторов
- **Безопасность** — JWT с разделением типов токенов, trusted proxy validation, restricted CORS

## Быстрый старт

### Локально (SQLite, без Docker)

```bash
git clone https://github.com/your-org/link-shortener.git
cd link-shortener
uv sync                                    # ставит зависимости и сам проект
cp .env.example .env                       # задайте SECRET_KEY и SHORT_CODE_PEPPER
uv run flask alembic upgrade head          # создать схему БД
uv run flask db load-base-roles            # создать роли guest/user/analyst/admin
uv run flask create-admin --email admin@example.com --password secret
uv run flask run
```

### В Docker (PostgreSQL + Redis + Celery)

```bash
cp .env.example .env.docker
```

В `.env.docker` задайте — иначе стек поднимется на SQLite без Redis и Celery,
а healthcheck базы не пройдёт:

```ini
ENV_FILE=.env.docker          # должен совпадать со значением --env-file
SECRET_KEY=<hex-строка 64 байта>
SHORT_CODE_PEPPER=<другой секрет>

DATABASE_TYPE=postgresql
DATABASE_HOST=db
DATABASE_NAME=db_shortener    # без расширения .db — это имя базы, не файл
DATABASE_USER=shortener
DATABASE_PASSWORD=<пароль>

REDIS_ENABLED=true
REDIS_PASSWORD=<пароль>
CELERY_ENABLED=true

DOMAIN=localhost:5000         # обязательно при HOST=0.0.0.0
```

```bash
docker compose --env-file .env.docker up -d --build
docker compose --env-file .env.docker exec app flask db load-base-roles
docker compose --env-file .env.docker exec app \
    flask create-admin --email admin@example.com --password secret
```

Миграции применяются автоматически: сервис `migrations` выполняет
`alembic upgrade head` до старта приложения.

Откройте `http://localhost:5000/` — можно сокращать ссылки сразу без регистрации.

> Команда выше поднимает **стек для разработки**: dev-сервер Flask с
> отладчиком и смонтированными исходниками. Compose сам подхватывает
> `docker-compose.override.yml`, где это и задано. Порт привязан к
> `127.0.0.1`: отладчик Werkzeug — интерактивная консоль, и в сети ей делать
> нечего.
>
> **Продакшн-форма** — тот же стек без надстройки, то есть с явным
> перечислением базового файла:
>
> ```bash
> docker compose -f docker-compose.yml --env-file .env.docker up -d --build
> ```
>
> Тогда приложение запускается командой образа: gunicorn с потолком на
> запрос (`GUNICORN_TIMEOUT`), без отладчика и без монтирования исходников.

Подробнее: [docs/QUICKSTART.md](docs/QUICKSTART.md)

## API

| Метод | Эндпоинт | Требуемое разрешение | Описание |
|-------|----------|----------------------|----------|
| POST | `/api/v1/shorten` | `link:create` (есть у `guest`) | Создать короткую ссылку (гость или пользователь) |
| GET | `/api/v1/links/<code>` | Нет | Информация о ссылке. `owner_id`, `clicks` и `last_accessed` отдаются только владельцу, админу и держателю `stats:view_any`; остальным приходит `null`. Адрес, исходный URL и дата создания публичны |
| GET | `/api/v1/links/<code>/extended` | Владение, `admin:all` или `stats:view_any` | Расширенная аналитика. Аноним получает `401`, чужой вошедший — `403` |
| GET | `/api/v1/stats` | `stats:view_basic` (есть у `guest`) | Итоги по сервису. Разбивка `popular_links` дополнительно требует `stats:view_full`, иначе приходит пустым списком |
| GET | `/api/v1/links/mine` | `link:view_own` | Список ссылок пользователя (пагинация: `offset`, `limit`) |
| DELETE | `/api/v1/links/<code>` | `link:delete_own` для своей, `link:delete_any` для чужой | Удалить ссылку |
| GET | `/api/v1/stats/mine` | `link:view_own` | Личная статистика |
| POST | `/api/v1/batch/shorten` | `link:create` (есть у `guest`) | Пакетное создание ссылок. Правила те же, что у одиночного: гостевой лимит, TTL по умолчанию, дедупликация в пределах владельца. Всё, что не прошло — невалидный URL, остаток квоты, — возвращается поэлементной ошибкой в `results`; сам запрос отвечает `200`, весь пакет не отклоняется |
| POST | `/api/v1/auth/register` | Нет | Регистрация |
| POST | `/api/v1/auth/login` | Нет | Получить JWT токены |
| POST | `/api/v1/auth/refresh` | Refresh-токен (cookie или тело) | Обменять refresh-токен на новую пару |
| POST | `/api/v1/auth/logout` | Refresh-токен или Bearer | Завершить сессию |
| GET | `/api/v1/admin/health` | Admin | Проверка здоровья инфраструктуры |
| GET | `/api/v1/admin/users` | Admin | Список пользователей |
| GET | `/api/v1/admin/roles` | Admin | Список ролей |

### Коды отказа

`401` означает «запрос никем не аутентифицирован», `403` — «аутентифицирован,
но разрешения нет». Раньше оба случая отвечали `403`, и клиент не мог
отличить «войди» от «вход не поможет».

Анонимный запрос при этом не отвергается автоматически: он выполняется в
роли `guest`, поэтому разрешение, которое эта роль несёт, проходит проверку.
Подробнее — [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), раздел «Роль
`guest` и анонимные запросы».

Истёкшая ссылка отвечает `410` на всех путях — и на редиректе, и на обоих
информационных эндпоинтах.

### Что публично, а что нет

Публичны: адрес короткой ссылки, исходный URL, дата создания, срок жизни.
Этого достаточно, чтобы посмотреть, куда ведёт код, до перехода по нему.

Приватны: `owner_id` и трафик — `clicks`, `last_accessed` и всё, что из них
считается (`/extended` целиком). Счётчики закрыты вместе с идентификатором
не из осторожности: каждое поле `/extended` — арифметика над ними, поэтому
пока они были публичными, ограничение на `/extended` обходилось
калькулятором.

*Следствие для гостевых ссылок:* у них нет владельца, поэтому их счётчики
не видит никто, кроме администратора и держателя `stats:view_any` — в том
числе тот, кто эту ссылку создал.

### Ограничения ролей и анонимный доступ

Проверка `link:create` различает **атрибутированное** создание — ссылку,
привязанную к учётной записи. Она не мешает тому же человеку выйти из
аккаунта и сократить URL анонимно: сервис публичный, анонима сдерживает
гостевая квота, а не RBAC. Роль без `link:create` (например, `analyst`)
означает «этот аккаунт не создаёт ссылок», а не «этот человек не может
создать ссылку».

### Аутентификация

Токен предъявляется одним из двух способов — какой применим, зависит от клиента.

**Программный клиент** — заголовок `Authorization: Bearer <access_token>`.
Оба токена возвращаются в теле ответа `POST /api/v1/auth/login`, cookie-jar
держать не нужно:

```bash
TOKENS=$(curl -s -X POST http://localhost:5000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"user@example.com","password":"..."}')

ACCESS=$(echo "$TOKENS" | jq -r .access_token)
REFRESH=$(echo "$TOKENS" | jq -r .refresh_token)

curl http://localhost:5000/api/v1/links/mine -H "Authorization: Bearer $ACCESS"

# Продлить сессию: refresh-токен ротируется, сохраните новый
curl -X POST http://localhost:5000/api/v1/auth/refresh \
  -H 'Content-Type: application/json' \
  -d "{\"refresh_token\":\"$REFRESH\"}"

# Завершить сессию: достаточно access-токена
curl -X POST http://localhost:5000/api/v1/auth/logout \
  -H "Authorization: Bearer $ACCESS"
```

**Браузер** — HttpOnly-cookie, которые ставит тот же `login`. Страницы дашборда
отдаются сервером, а обычная навигация не может послать заголовок, поэтому для
веб-интерфейса это единственный работающий способ. JavaScript токен не видит и
нигде не хранит.

Принимается только access-токен: refresh-токен годится исключительно для
`POST /api/v1/auth/refresh`. Деактивация учётной записи отзывает доступ на
следующем же запросе, а не по истечении токена.

### Сессии и отзыв токенов

Каждый выданный refresh-токен несёт `jti`, которому соответствует строка в
таблице `refresh_sessions`. Отсюда:

- **Выход** отзывает сессию на сервере, а не только удаляет cookie. Вместе
  с ней перестают работать и выданные ею access-токены: каждый несёт claim
  `sid` с именем своей сессии, и оно проверяется на каждом запросе. Другие
  устройства остаются в системе.
- **Обмен токена ротирует его** — `POST /api/v1/auth/refresh` возвращает и
  новый access, и новый refresh, а предъявленный retired.
- **Повторное предъявление потраченного токена** означает, что он
  скопирован: оригинал и копию в этот момент не различить, поэтому
  отзывается **цепочка этого входа** — и только она. Остальные устройства
  не затрагиваются: иначе один найденный мёртвый токен стал бы способом
  разлогинить человека везде по требованию.
- **Блокировка аккаунта** отзывает все его сессии.

Строки истёкших сессий чистятся командой
`flask maintenance clean-sessions` — см. расписание обслуживания в
[OPERATIONS_AND_MIGRATIONS.md](docs/OPERATIONS_AND_MIGRATIONS.md).

### CSRF

Запрос, аутентифицированный **cookie**, на любом методе кроме
`GET/HEAD/OPTIONS/TRACE` проходит три проверки: значение читаемой cookie
`csrf_token` дублируется в заголовке `X-CSRF-Token`; токен подписан
`SECRET_KEY` и привязан к пользователю, которому выдан; названный браузером
`Origin` (или `Referer`) входит в список разрешённых. Иначе —
`403 CSRF_TOKEN_INVALID`.

Запрос с валидным `Authorization: Bearer` эту проверку не проходит вовсе:
клиент, который умеет выставить заголовок, к CSRF не уязвим. Для curl и
скриптов ничего не меняется.

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

Проект использует три уровня тестирования:

### Уровень 1: Unit-тесты (моки, изолированно)

```bash
uv run pytest tests/unit/ -v
```

### Уровень 2: Интеграционные тесты (реальная in-memory SQLite)

```bash
uv run pytest tests/integration/ --ignore=tests/integration/docker/ -v
```

Без `--ignore` соберётся и уровень 2b, которому нужен Docker.

### Уровень 2b: Интеграционные тесты (реальный PostgreSQL + Redis)

Docker-сервисы поднимаются автоматически:

```bash
uv run pytest tests/integration/docker/ -v
```

### Уровень 3: E2E тесты (полные пользовательские сценарии)

```bash
uv run pytest tests/e2e/ -v
```

### Все тесты вместе

```bash
uv run pytest tests/ -v

# С покрытием
uv run pytest tests/ --cov=src/link_shortener --cov-report=term-missing
```

Тесты: 1229 (unit + integration + e2e), покрытие: 88%

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

`FLASK_ENV` выбирает **профиль** — класс конфигурации из
`infrastructure/configs/app/`: `development`, `staging`, `production`,
`testing`. Профиль задаёт умолчания, а `.env` их переопределяет.

Приоритет, побеждает верхний:

1. настоящая переменная окружения (`export`, `environment:` в compose);
2. `.env.<профиль>` — например `.env.production`;
3. `.env`;
4. умолчание профиля в коде.

Профиль `testing` намеренно игнорирует `.env`-файлы — автотесты должны давать
одинаковый результат на любой машине.

Полный список переменных с описаниями — в `.env.example`. Ключевые:

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `FLASK_ENV` | development | Профиль конфигурации |
| `SECRET_KEY` | случайный | Подпись JWT. Без явного значения токены умирают при рестарте |
| `SHORT_CODE_PEPPER` | случайный | Соль для генерации кодов. Должна совпадать на всех инстансах |
| `GUEST_LINK_LIMIT` | 10 | Макс. ссылок для гостя за окно. Применяется под блокировкой по адресу гостя, поэтому одновременные запросы не тратят одну и ту же квоту дважды — на PostgreSQL; на SQLite лимит совещательный |
| `GUEST_LINK_WINDOW_DAYS` | 1 | Окно подсчёта (дни) |
| `DEFAULT_GUEST_TTL_SECONDS` | 604800 | Время жизни гостевых ссылок (7 дней) |
| `CACHE_LINK_TTL` | 3600 | TTL кэша ссылок, сек (в development — 20) |
| `COOKIE_SECURE` | false | Secure-флаг для cookie (true в production) |
| `TRUSTED_PROXIES` | (пусто) | Доверенные прокси для X-Forwarded-For |
| `DOMAIN` | (пусто) | Публичный домен. Обязателен при `HOST=0.0.0.0` |

## Документация

- [Быстрый старт](docs/QUICKSTART.md) — пошаговая инструкция первого запуска
- [Руководство разработчика](docs/DEVELOPER_GUIDE.md) — архитектура, паттерны, как вносить изменения
- [Архитектура](docs/ARCHITECTURE.md) — подробное описание системы
- [Эксплуатация](docs/OPERATIONS_AND_MIGRATIONS.md) — CLI команды, миграции, обслуживание

## Лицензия

MIT
