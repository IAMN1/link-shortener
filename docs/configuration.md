# Configuration

Looked up rather than read. The exhaustive list — every variable, one line
of description each — is [`.env.example`](../.env.example); this page covers
the rules around it and the settings that bite.

[All docs](README.md) · [Getting started](getting-started.md) ·
[Operations](operations.md)

## Profiles and precedence

`FLASK_ENV` picks a **profile** (a configuration class), the profile sets
defaults, and `.env` overrides them.

```mermaid
flowchart LR
    E["Environment variable<br/>export · environment:"] --> P1
    P1[".env.&lt;profile&gt;"] --> P2[".env"]
    P2 --> P3["The profile's default<br/>in infrastructure/configs/app/"]
```

Leftmost wins.

| Profile | For | Notably |
|---|---|---|
| `development` | Local work | SQLite, in-memory cache, Redis off, debug on |
| `staging` | Pre-production | PostgreSQL required, secrets required, logs to `/var/log/link_shortener/staging` |
| `production` | The real thing | PostgreSQL required, secrets required, `Secure` cookies, gunicorn |
| `testing` | The suite | **Ignores `.env` and the environment entirely** |

> [!IMPORTANT]
> The `testing` profile reads no environment at all. That is deliberate: a
> test must give the same answer on every machine. If you are wondering why
> a variable "does not apply" under pytest, this is why.

## What the deployed profiles refuse to start without

With an empty environment, `staging` and `production` refuse to start and
name five reasons at once. `development` and `testing` come up with nothing
set.

| Variable | Why it is mandatory there |
|---|---|
| `SECRET_KEY` | Signs JWTs, sessions and cache entries. The default is random per process, so workers disagree and tokens die on restart |
| `SHORT_CODE_PEPPER` | Salts code generation. Differing values across instances produce different codes for one URL |
| `DOMAIN` | The host every short link is built from. Without it the address comes from `HOST:PORT` — where the process listens, not where callers arrive |
| `DATABASE_TYPE=postgresql` + host, name, user — or one `DATABASE_URL` | SQLite there would mean an empty new file, and the service answering as though the data had never existed |
| `REDIS_URL` | These profiles default `REDIS_ENABLED=true`, and an enabled Redis with no address is a cache and a limiter with nothing to connect to |

Conditionally mandatory: `MAIL_HOST` and `MAIL_FROM` when
`MAIL_ENABLED=true`. `production` additionally refuses to submit mail
without TLS — a submission in the clear carries the confirmation link to
anyone on the path.

```bash
uv run flask security generate-secrets   # prints both secrets, ready to paste
```

## Storage locations

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_DIR` | `datas/databases` | Where SQLite files live. Relative to the project root; absolute is taken as it stands and works inside a container too, where there is no project root |
| `DATABASE_NAME` | `db_shortener` | A file name for SQLite, a database name for PostgreSQL. An absolute path here wins over `DATABASE_DIR` |
| `LOG_DIR` | `datas/logs` | Where journals go when `LOG_TO_FILE=true`. Same rule: relative to the root, absolute as it stands |

Both directories are created on demand. Relative paths are anchored to the
project root rather than to the working directory of the process — read
against the cwd, the same setting names a different directory for every
process, and `flask` started from `src/` opened a second, empty database
without a word about it.

| What you set | Where the file lands |
|---|---|
| `DATABASE_NAME=app.db` | `<root>/datas/databases/app.db` |
| `DATABASE_DIR=/var/lib/shortener` | `/var/lib/shortener/app.db` |
| `DATABASE_NAME=/srv/live.db` | `/srv/live.db`; `DATABASE_DIR` is not read |
| `DATABASE_URL=sqlite:////srv/live.db` | `/srv/live.db`; no other `DATABASE_*` is read |

## Guest links

| Variable | Default | |
|---|---|---|
| `GUEST_LINK_LIMIT` | 10 | Links per window for one address. Applied under a lock on the guest identifier, so concurrent requests cannot spend the same quota twice — on PostgreSQL; on SQLite the limit is advisory |
| `GUEST_LINK_WINDOW_DAYS` | 1 | The window |
| `DEFAULT_GUEST_TTL_SECONDS` | 604800 | Seven days |

## Security

| Variable | Default | |
|---|---|---|
| `SECRET_KEY` | random per process | Signs JWTs, sessions, cache entries |
| `SHORT_CODE_PEPPER` | random per process | Salts code generation |
| `COOKIE_SECURE` | `false`, `true` in production | The `Secure` flag on auth cookies |
| `SESSION_COOKIE_SECURE` | `false`, `true` in production | The same for Flask's session cookie |
| `SESSION_COOKIE_SAMESITE` | `Lax` | |
| `SESSION_COOKIE_HTTPONLY` | `true` | |
| `CORS_ORIGINS` | `http://localhost:5000,http://127.0.0.1:5000` | Origins allowed to send credentials |
| `TRUSTED_PROXIES` | empty | Only from these is `X-Forwarded-For` believed |

> [!WARNING]
> `CORS_ORIGINS` holds both spellings of the loopback on purpose. The CSRF
> layer compares the browser's `Origin` against this list before letting an
> unsafe cookie-authenticated request through. With `localhost` alone,
> opening `http://127.0.0.1:5000` gives a working landing page — an
> anonymous caller does not go through CSRF — and "CSRF token missing or
> invalid" on every form the moment you sign in. Measured on the Docker
> stack.

## Rate limits

| Endpoint | Limit | Period | For |
|---|---|---|---|
| `auth.login` | 5 | 60 s | Brute force |
| `auth.register` | 3 | 3600 s | Spam |
| `auth.refresh_token` | 10 | 60 s | Replay |
| `auth.logout` | 20 | 60 s | |
| `auth.verify_email` | 10 | 60 s | Guessing a confirmation token |
| `auth.resend_verification` | 3 | 3600 s | Mail on demand |
| `api.create_short_link` | 30 | 60 s | Creating links |
| `api.batch_create` | 5 | 60 s | Creating in bulk |
| `api.get_link_info` | 100 | 60 s | Reading a link |
| `api.get_extended_link_info` | 50 | 60 s | Reading with metrics |
| `api.get_stats` | 10 | 60 s | Service counters |
| `redirect_to_original` | 200 | 60 s | Redirects |

Anything absent from the table goes by `DEFAULT_RATE_LIMIT` — 100 requests
per `DEFAULT_RATE_LIMIT_PERIOD` (60 seconds).

`RATE_LIMIT_AUTH_DISABLED=true` silences all six `auth.*` rows at once. It
is a development switch; in production it must stay off, or there is no
protection against password guessing.

> [!NOTE]
> This table is parsed by `test_documented_rate_limits.py` and held against
> `BaseConfig.RATE_LIMITS`. Publishing a limit the service does not enforce
> fails the suite — a limit is a security decision, and a document naming
> the wrong one is worse than a document naming none, because it is
> believed.

<details>
<summary>Why <code>/health</code> cannot be given a limit, and what the start-up check rejects</summary>

A probe is how an orchestrator learns whether an instance is alive, and it
cannot tell `429` from a real failure: throttling the probe means a busy
service gets restarted. `health` therefore sits in `EXEMPT_ENDPOINTS`
(`web/middleware/rate_limit.py`), and the exemption is checked **before** the
limit.

A `RATE_LIMITS` entry for an exempt endpoint does not fail quietly: probe
after probe, no `429`, and the setting reads as protection that is not
there. Every key is therefore held against the routing table at start-up,
and the application **will not come up** if a key is unreachable — exempt,
served from `/static/`, or pointing at nothing.

Values are checked too; without that, each bad shape survives until the
first request and breaks in its own way:

| Value | What happens |
|---|---|
| `10`, `(5,)`, `("5", 60)` | `500` on every request to that endpoint |
| `(0, 60)` | Refuses **everyone, always** |
| `(5, -60)` | The window start moves into the future, every mark falls outside it, and nothing is throttled **at all** |

`("5", 60)` deserves its own mention: against Redis it is not a defect — its
script coerces the number — while against the in-memory cache it is a `500`.
A setting that works in production and fails in development takes longer to
find than one that works nowhere.

**A typo in an endpoint name is the likeliest case and the quietest.**
`auth.login` written as `auth.log_in` raises nothing: the endpoint keeps
answering, but on the default limit — and the protection against password
guessing is gone while the configuration says it is there.

</details>

## Cache

| Variable | Default | |
|---|---|---|
| `CACHE_ENABLED` | `true` | `false` turns every cache call into a no-op |
| `REDIS_ENABLED` | `false` in development, `true` in deployed profiles | Redis or the in-memory implementation |
| `REDIS_URL` | — | Mandatory when Redis is on |
| `CACHE_LINK_TTL` | 3600 | Seconds a link object is kept |
| `CACHE_STATS_TTL` | 300 | Seconds service statistics are kept — and how far the click counter can lag |

## Mail

| Variable | Default | |
|---|---|---|
| `MAIL_ENABLED` | `true` | With it off, registration still answers `202` and no message leaves |
| `MAIL_HOST`, `MAIL_PORT` | `localhost`, 1025 in development | Aimed at the Mailpit catcher |
| `MAIL_USE_TLS` / `MAIL_USE_SSL` | `false` in development | `production` requires one of them |
| `MAIL_FROM` | — | Mandatory when mail is on |
| `UNVERIFIED_ACCOUNT_TTL_HOURS` | 24 | How long an unconfirmed account is kept before `maintenance clean-unverified` removes it |

## Compose-only variables

Read by `docker compose`, not by the application.

| Variable | |
|---|---|
| `ENV_FILE` | Which env file the services load; must match what you pass to `--env-file` |
| `COMPOSE_FILE` | Which compose files make up the stack. Set because they live in `dockers/` |
| `COMPOSE_PROFILES` | Which of `db`, `cache`, `broker`, `mail` to run yourself |
| `APP_HOST_PORT`, `DATABASE_HOST_PORT`, `REDIS_HOST_PORT`, `MAILPIT_UI_PORT` | Where each service is published on the host |
| `APP_SRC_PATH`, `LOG_HOST_PATH` | What the dev overlay mounts. Relative to `dockers/`, hence the `../` |

## Where the numbers come from

Defaults live in `infrastructure/configs/app/base.py` and are overridden per
profile in `development.py`, `staging.py` and `production.py`. Every one is
declared through a lazy environment descriptor, so a value is read when it
is used and a profile can narrow an optional setting into a mandatory one —
which is what `staging` and `production` do with the secrets.
