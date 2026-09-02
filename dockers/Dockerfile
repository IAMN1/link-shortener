# syntax=docker/dockerfile:1

# The dependency list is exported from `uv.lock` during the build rather than
# kept beside it in the repository. A second copy of the lock is a copy that
# goes stale silently: Dependabot updates the two independently -- the
# September 2026 group bumped 23 packages in the exported file and none in
# the lock -- and CI would then test one set of packages while the image
# shipped another.
#
# A stage of its own, so `uv` reaches neither the builder's site-packages nor
# /usr/local/bin: the runtime stage copies both of those wholesale.
FROM python:3.12-slim-bookworm AS requirements
COPY --from=ghcr.io/astral-sh/uv:0.11.14 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
# --frozen reads the lock as it stands and resolves nothing, so the image
# carries exactly the packages CI installed. `browser` and `contract` are
# test-only groups and stay out.
RUN uv export --format requirements-txt --no-hashes --no-emit-project \
        --frozen --no-group browser --no-group contract \
        -o /requirements.txt

FROM python:3.12-slim-bookworm AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*


WORKDIR /app
COPY --from=requirements /requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The package is installed apart from its dependencies: the export above
# only lists those (`uv export --no-emit-project`), and without this step
# `link_shortener` does not import in the image.
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

# Alembic's configuration and revisions are needed in the image: otherwise
# `alembic upgrade head` only works where they are mounted as a volume.
COPY alembic.ini ./
COPY ./migrations ./migrations/

# `FLASK_APP` lives here rather than in an env file, and the image needs the
# file for the same reason the host does: without it `flask <anything>` inside
# a container answers "Could not locate a Flask application" unless whatever
# env file the deployment happens to use names the application. That was the
# fault this move was made to close, and it stayed open in the image --
# measured by running `flask --help` in a container with no `FLASK_APP` in its
# environment.
COPY .flaskenv ./

RUN groupadd --gid 1000 appuser && \
    useradd --create-home --uid 1000 --gid 1000 appuser && \
    mkdir -p /app/logs && \
    chown -R appuser:appuser /app

# Path from the project root: the build context is the root rather than
# this file's directory, because the image takes src/, migrations/ and
# alembic.ini.
COPY dockers/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 5000

ENTRYPOINT ["/entrypoint.sh"]

# The production command: gunicorn.
#
# --worker-class sync is set explicitly: --timeout interrupts a stuck
# request only on sync workers; on gthread a request can run forever.
#
# --timeout is the only thing that interrupts a call to a database that has
# hung rather than fallen over: its kernel keeps acknowledging packets, so
# neither the server's statement_timeout nor TCP keepalive fires.
#
# --graceful-timeout is strictly smaller than --timeout, or a worker
# finishing a request during a restart is killed before it is done.
#
# The application specification is in single quotes: without them `sh`
# parses `create_app()` as a function declaration.
CMD ["sh", "-c", "exec gunicorn --bind ${HOST:-0.0.0.0}:${PORT:-5000} --workers ${GUNICORN_WORKERS:-4} --worker-class ${GUNICORN_WORKER_CLASS:-sync} --timeout ${GUNICORN_TIMEOUT:-30} --graceful-timeout ${GUNICORN_GRACEFUL_TIMEOUT:-20} --access-logfile - --error-logfile - 'link_shortener.web.app_factory:create_app()'"]
