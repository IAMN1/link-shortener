# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*


WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Пакет ставится отдельно от зависимостей: requirements.txt их только
# перечисляет (`uv export --no-emit-project`), и без этого шага
# `link_shortener` в образе не импортируется.
COPY pyproject.toml README.md ./
COPY ./src ./src/
RUN pip install --no-cache-dir --no-deps .

FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    gosu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages/ /usr/local/lib/python3.12/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/

COPY ./src ./src/

# Конфиг и ревизии Alembic нужны в образе: иначе `alembic upgrade head`
# работает только там, где они примонтированы томом.
COPY alembic.ini ./
COPY ./migrations ./migrations/

RUN groupadd --gid 1000 appuser && \
    useradd --create-home --uid 1000 --gid 1000 appuser && \
    mkdir -p /app/logs && \
    chown -R appuser:appuser /app

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 5000

ENTRYPOINT ["/entrypoint.sh"]

# Продакшн-команда: gunicorn.
#
# --worker-class sync задан явно: --timeout прерывает зависший запрос только
# на sync-воркерах, у gthread запрос может идти бесконечно.
#
# --timeout — единственное, что прерывает обращение к зависшей, а не упавшей
# БД: её ядро подтверждает пакеты, поэтому не срабатывают ни серверный
# statement_timeout, ни TCP-keepalive.
#
# --graceful-timeout строго меньше --timeout, иначе воркер, доигрывающий
# запрос при перезапуске, будет убит раньше, чем закончит.
#
# Спецификация приложения в одинарных кавычках: без них `sh` разбирает
# `create_app()` как объявление функции.
CMD ["sh", "-c", "exec gunicorn --bind ${HOST:-0.0.0.0}:${PORT:-5000} --workers ${GUNICORN_WORKERS:-4} --worker-class ${GUNICORN_WORKER_CLASS:-sync} --timeout ${GUNICORN_TIMEOUT:-30} --graceful-timeout ${GUNICORN_GRACEFUL_TIMEOUT:-20} --access-logfile - --error-logfile - 'link_shortener.web.app_factory:create_app()'"]