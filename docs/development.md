# Development

Working on the code: the patterns you will meet, how the frontend decides
what to offer, and the load profile with the numbers it produced.

[All docs](README.md) · [Architecture](architecture.md) ·
[Testing](testing.md) · [Decisions](decisions.md)

## State of the project

The backend is complete: single and batch creation, guest and authenticated
modes with TTL, registration with address confirmation, JWT authentication,
deletion with cache invalidation, pagination, an admin panel, rate limiting,
health monitoring and a maintenance CLI.

The frontend is at the same level. What a page shows is decided by a
**permission**, not by a role name — see [below](#the-frontend-asks-the-server).

**Boundaries left in place deliberately:**

| | |
|---|---|
| No HTTPS in development | In the production form, TLS terminates at the proxy in front of the service |
| No link previews or OG tags | — |
| No API version above v1 | — |
| Pool values reach SQLAlchemy as given | A negative `DATABASE_MAX_OVERFLOW` breaks engine construction with an unhelpful error |
| The load profile was measured on one machine | What transfers is the conclusions, not the numbers |
| pytest does not collect the live runs | `python_files = "test_*.py"` does not match their names |

## Patterns in the code

| Pattern | Where | Note |
|---|---|---|
| **Repository** | `domain/repositories/` declares, `infrastructure/database/` implements | The domain never sees SQLAlchemy |
| **Unit of Work** | `uow.links`, `uow.users`, explicit `commit()` | Leaving the context without a commit rolls back |
| **Use case** | One scenario per class, extending `BaseUseCase` | Dependencies are dataclass fields, so the DI container assembles them |
| **Facade** | `LinkService`, `AdminService` | What the web layer talks to; keeps controllers free of orchestration |
| **Ports and adapters** | `application/ports/` | Cache, logger, mailer, queue — each has a null implementation |
| **DI container** | `infrastructure/di/` | Lazy: a component is built when first asked for |
| **Value objects** | `OriginalUrl`, `ShortCode`, `Email`, `UrlHash` | Validation lives in the type, so an invalid value cannot exist |
| **Lazy env descriptors** | `infrastructure/configs/app/env.py` | A setting is read when used, which is what lets a profile narrow it |

## Key files

| File | |
|---|---|
| `web/app_factory.py` | The application factory; wires everything together |
| `infrastructure/di/container.py` | The container and every component's construction |
| `infrastructure/configs/app/base.py` | Every setting, with environment overrides |
| `infrastructure/database/role_loader.py` | RBAC from YAML into the database |
| `web/security/template_access.py` | `can(...)` for the markup |
| `web/middleware/csrf.py` | The double-submit implementation |
| `migrations/versions/0001_initial_schema.py` | The baseline: the whole schema from nothing |

## The frontend asks the server

Everything a page shows or hides is decided by one question — the same one
the route asks.

```jinja
{% if can('link:create') %}
    <a href="{{ url_for('dashboard.create_link_form') }}">Create Link</a>
{% endif %}
```

`can` lives in `web/security/template_access.py` and asks
`g.authorization_service`, which is what `@require_permission` stands on.
Answers are memoised per request: the anonymous branch opens a Unit of Work
to read the `guest` role, and a sidebar asks about seven permissions.

**Why not role names.** That is how it was: `{% if 'analyst' in
g.current_user.roles %}`. The server checks permissions, so the two asked
different questions and drifted apart wherever a role held a permission its
name did not imply. Measured by walking the running product: an analyst was
offered "Create Link" in two menus and on two pages (it holds no
`link:create` — 403 every time), and a plain user was offered no way to
reach the service statistics it may read. A role created through the panel
itself was invisible to the markup entirely — its name is in no template.

**What the markup must not decide.** A permission does not always answer the
page's whole question. Extended analytics for a link is ownership,
`admin:all` or `stats:view_any`, and `can` knows nothing about ownership; the
page keys on `link:view_own` ("I have links of my own") and labels the field
honestly. Deletion is the same: `link:delete_own` versus `link:delete_any` is
chosen by the use case from the row it is deleting, and the markup only
passes its answer to the script through a `data` attribute, because the
column is drawn by JS.

**What holds it.** `tests/integration/web/test_templates/` renders pages with
real DTOs from real services and asserts on what a person would read. Two
defects that survived 95% coverage lived exactly where the Python tests do
not look: `{{ role.name }}` over a list of strings prints nothing, and
`user.roles|map(attribute='name')` matches nothing — so the roles column was
blank for every account, and the edit form opened with every box clear and
saved whatever the operator happened to tick.

## The design system

Two stylesheets, no framework, no build step. The subject is redirection: a
short code stands in for a destination the way a route number stands in for
a road, so a code is set on a green shield with a hairline keyline wherever
it appears — in a table, on the landing page, in an admin's list. Headings
are condensed and tight, the way words on a sign are. Yellow appears only
where road paint appears: to caution.

Both themes are defined with tokens on `:root`, and the dark one redefines
only the tokens under `prefers-color-scheme: dark`. A colour written into a
`style` attribute cannot be reached by that — which is how the landing
page's result card kept a light grey at 1.7:1 contrast on the dark surface
until it was caught.

## Load profile

Measured once, on one machine, and recorded together with it — without that
the numbers would be opinions again.

**Where.** Apple M5, 10 cores, 16 GB; Docker Desktop 29.6.2 limited to 10
CPUs and 8 GB; macOS 26.5. The production form of the stack
(`docker compose -f dockers/docker-compose.yml`), that is gunicorn with
`--worker-class sync`, PostgreSQL 15 and Redis 7 as containers of the same
stack, `FLASK_ENV=development`, Celery on.

**With what.** `tests/load/locustfile.py`, dependency group `load`:

```bash
uv sync --group load
uv run locust -f tests/load/locustfile.py --headless \
    -u 50 -r 50 -t 30s -H http://localhost:5000 RedirectUser
```

Four scenarios to choose from as the last argument: `RedirectUser`,
`CreateUser`, `HealthUser`, `MixedUser` (the last mixes 90/9/1).

> [!IMPORTANT]
> The profile gives every request its own `X-Forwarded-For`, and the stack
> under test must trust the address locust comes from. Otherwise you are
> measuring the rate limiter, not the service: it counts per address, and
> twenty users behind one address returned `429` for 85% of requests.

### Gunicorn workers

Redirect, 50 concurrent users, milliseconds:

| `GUNICORN_WORKERS` | req/s | p50 | p95 | p99 |
|---|---|---|---|---|
| 1 | 743 | 62 | 77 | 93 |
| 2 | 973 | 47 | 61 | 78 |
| 4 | 1313 | 34 | 49 | 65 |
| 8 | **1519** | 29 | 45 | 58 |
| 16 | 1406 | 28 | 51 | 86 |

The mixed scenario, same 50 users: 2 → 542 req/s at p99 990 ms, 4 → 791 at
p99 410, 8 → 1027 at p99 85.

**What follows.** The ceiling here is eight workers on ten cores, and
sixteen is worse than eight on both throughput and tail. The old rule of
thumb "2 × cores + 1" would have given twenty-one, well past the knee; the
template and the reference now say "about the number of cores, and no more".

The default is **4** rather than 8: it yields 86% of this machine's ceiling
and stays sensible on a two-core box.

### Connection pool

Link creation, 4 workers, 50 users; the last column is how many connections
PostgreSQL counted:

| `DATABASE_POOL_SIZE` | req/s | p50 | p99 | connections |
|---|---|---|---|---|
| 1 | 631 | 73 | 110 | 15 |
| 2 | 605 | 73 | 260 | 15 |
| 5 | 609 | 75 | 150 | 15 |
| 20 | 615 | 74 | 130 | 15 |

On the redirect path the same: 1245, 1277 and 1306 req/s at pool 1, 5 and 20.

**What follows.** Pool size decides nothing here, and the reason is the
worker class: `sync` carries one request at a time, so a process holds one
connection however many it is allowed. The pool is a ceiling, not a
reserve, and the ceiling was never reached.

The value was lowered from 20 to 5 (and `DATABASE_MAX_OVERFLOW` from 10 to
5) not for speed but because the ceiling multiplies by the number of
workers: 20 + 10 across eight processes is 240 connections against the
hundred PostgreSQL allows by default. Five per process across four workers
is forty, with room either way.

### Cache

Redirect, 4 workers:

| `CACHE_ENABLED` | req/s | p50 | p95 | p99 |
|---|---|---|---|---|
| `true` | 1320 | 35 | 45 | 64 |
| `false` | 897 | 51 | 65 | 97 |

The cache is worth 47% of the hot path's throughput — which is why
`CACHE_LINK_TTL` and `CACHE_STATS_TTL` deserve non-zero values. The
particular 3600 and 300 are a freshness-versus-hit-rate choice rather than a
performance one, and this run does not measure them.

## API documentation

- `GET /api/openapi.json` — an OpenAPI 3.1 document. Request and response
  bodies are generated from the same Pydantic models the endpoints validate
  against, so a field that changes shape changes shape here with it.
- `GET /api/docs` — the same document as a page. No viewer is bundled: that
  is a megabyte and a half of vendored assets, or a script tag pointing at
  somebody else's CDN, in a service whose whole job is to be a small
  redirect.

`tests/integration/web/controllers/test_api_docs.py` holds the document
against the real URL map, so a new endpoint is a failing test rather than an
undocumented one. Administration is included — 24 paths, 29 operations, of
which 14 are administrative. Each names the permission that opens it, which
is the one thing a reader cannot recover from the shapes.

The only body written by hand is `GET /api/v1/admin/health`, which the
endpoint assembles as a dict; two tests hold that schema and the live
answer together in both directions.

## Adding something

| You want | Where it goes |
|---|---|
| A scenario | A use case in `application/use_cases/`; wire it in the container |
| An endpoint | A controller method, a Pydantic schema, `@require_permission`, and an entry in `web/schemas/openapi.py` |
| A permission | `domain/system_permissions.py`, then `infrastructure/configs/rbac/roles.yaml` |
| A page | A template extending `dashboard/base.html`, a script in `static/js/pages/`, and `can(...)` around whatever it offers |
| A setting | `infrastructure/configs/app/base.py` through an env descriptor, plus a line in `.env.example` |

Every one of those has a test that fails if you skip the last step.
