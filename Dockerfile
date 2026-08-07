# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*


WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Сам пакет ставится отдельно от зависимостей: requirements.txt их только
# перечисляет (`uv export --no-emit-project`), поэтому без этого шага
# `link_shortener` в образе не импортируется вовсе. Продакшн-команда падала
# на `ModuleNotFoundError` — незаметно, потому что docker-compose
# перекрывает её на `flask run` с примонтированным ./src.
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

# Конфиг и ревизии Alembic должны быть в образе, иначе `alembic upgrade head`
# работает только там, где они примонтированы томом (docker-compose),
# и недоступен при обычном развёртывании образа.
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

# Команда по умолчанию – для продакшена (gunicorn)
#
# --worker-class sync задан явно, а не оставлен на умолчание: --timeout
# гарантированно убивает зависший запрос только на sync-воркерах. У gthread
# один запрос может идти бесконечно, и потолок ниже стал бы декорацией.
#
# --timeout нужен потому, что серверный statement_timeout не выполняется
# замороженной (а не упавшей) БД: её ядро подтверждает пакеты, поэтому и
# TCP-keepalive не срабатывает. Тогда единственное, что ещё способно
# прервать ожидание, — надзор за самим процессом. Замерено: при docker pause
# на контейнере БД редирект не отвечал 120 с, а тридцати таких запросов
# хватает, чтобы исчерпать пул.
#
# --graceful-timeout строго меньше --timeout: иначе воркер, честно
# доигрывающий запрос при перезапуске, будет убит обычной проверкой раньше,
# чем успеет закончить.
# Спецификация приложения в одинарных кавычках: без них `sh` разбирает
# `create_app()` как объявление функции и падает с
# `Syntax error: "(" unexpected`, не дойдя до gunicorn.
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-5000} --workers ${GUNICORN_WORKERS:-2} --worker-class ${GUNICORN_WORKER_CLASS:-sync} --timeout ${GUNICORN_TIMEOUT:-30} --graceful-timeout ${GUNICORN_GRACEFUL_TIMEOUT:-20} --access-logfile - --error-logfile - 'link_shortener.web.app_factory:create_app()'"]