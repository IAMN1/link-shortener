# Быстрый старт

Пошаговая инструкция по запуску сервиса с нуля.

## Предварительные требования

- [Docker](https://docs.docker.com/get-docker/) и Docker Compose v2+
- Git

## Шаг 1: Клонирование репозитория

```bash
git clone https://github.com/your-org/link-shortener.git
cd link-shortener
```

## Шаг 2: Настройка окружения

Отредактируйте `.env` в корне проекта. Минимально задайте:

```ini
SECRET_KEY=<случайная hex-строка 64 байта>
SHORT_CODE_PEPPER=<другой секретный ключ>
DATABASE_PASSWORD=<надёжный пароль>
REDIS_PASSWORD=<надёжный пароль>
```

Необязательные настройки гостевых ссылок (значения по умолчанию):

```ini
GUEST_LINK_LIMIT=10              # Макс. ссылок для гостя за окно
GUEST_LINK_WINDOW_DAYS=1         # Размер окна (дни)
DEFAULT_GUEST_TTL_SECONDS=604800 # Гостевые ссылки живут 7 дней
```

> Никогда не коммитьте реальные секреты в репозиторий.

## Шаг 3: Сборка образов

```bash
docker compose build --no-cache
```

## Шаг 4: Запуск инфраструктуры

```bash
docker compose up -d db redis
```

Дождитесь статуса `healthy` в выводе `docker compose ps`.

## Шаг 5: Применение миграций

```bash
docker compose run --rm migrations alembic upgrade head
```

Создаст все таблицы и заполнит системные роли (guest, user, analyst, admin) с разрешениями.

## Шаг 6: Запуск всех сервисов

```bash
docker compose up -d
```

Запущенные сервисы:
- `app` — Flask-приложение на порту 5000 (с healthcheck)
- `celery_worker` — фоновый обработчик задач

Проверьте логи:
```bash
docker compose logs app
```

## Шаг 7: Создание администратора

```bash
docker compose exec app flask create-admin --email admin@example.com --password your_password
```

## Шаг 8: Использование приложения

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
| Мои ссылки | Все пользователи | Просмотр, управление, удаление ссылок |
| Моя статистика | Все пользователи | Личная аналитика кликов |
| Создать ссылку | Все пользователи | Форма с выбором TTL |
| Статистика сервиса | analyst, admin | Глобальная статистика |
| Пользователи | admin | Управление пользователями |
| Роли | admin | Управление ролями и разрешениями |
| Проверка здоровья | admin | Статус БД, Redis, Celery |

## Локальная разработка (без Docker)

1. Установите Python 3.12, PostgreSQL, Redis
2. Установите [uv](https://docs.astral.sh/uv/getting-started/installation/):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
3. Установите зависимости:
   ```bash
   uv sync --dev
   ```
4. Создайте базу данных и настройте `.env` с `DATABASE_HOST=localhost`
5. Примените миграции:
   ```bash
   alembic upgrade head
   ```
6. Запустите приложение:
   ```bash
   uv run flask run
   ```
7. Запустите тесты:
   ```bash
   uv run pytest tests/ -v
   ```
8. (Опционально) Запустите Celery worker:
   ```bash
   celery -A link_shortener.infrastructure.task_queue.celery_app worker --loglevel=info
   ```
