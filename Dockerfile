# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*


WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    gosu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages/ /usr/local/lib/python3.12/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/

COPY ./src ./src/

RUN groupadd --gid 1000 appuser && \
    useradd --create-home --uid 1000 --gid 1000 appuser && \
    mkdir -p /app/logs && \
    chown -R appuser:appuser /app

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 5000

ENTRYPOINT ["/entrypoint.sh"]

# Команда по умолчанию – для продакшена (gunicorn)
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-5000} --workers ${GUNICORN_WORKERS:-2} --access-logfile - --error-logfile - link_shortener.web.app_factory:create_app()"]