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
| `infrastructure/configs/app/base.py` | Every setting the service reads, bar four, and none of the four is one a profile could hold: `CELERY_BROKER_TIMEOUT` is the worker's own and lives in `configs/celery/`, `FLASK_ENV` picks the profile rather than sitting in one, `ALEMBIC_DATABASE_URL` is the handover one migration reads in `configs/app/migration_url.py`, and `FLASK_RUN_FROM_CLI` is set by the `flask` command and read in `configs/app/factory.py` to see whether `.env` is already loaded |
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
to read the `guest` role, and a sidebar asks about eight permissions.

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

Measured three times, on one machine, and recorded together with it —
without that the numbers would be opinions again. The first set was taken
on 2026-08-14, before a redirect recorded anything; the second on
2026-08-19, on a tree where every redirect writes a visit. Both are
printed where they differ, because the difference is the point. The third,
2026-08-20, asks a different question — not where the service stops but
which resource stops it — and is under *What saturates first* below.

**Where.** Apple M5, 10 cores, 16 GB; Docker Desktop 29.6.2 limited to 10
CPUs and 8 GB; macOS 26.5. Identical to the first run, which is what makes
the two comparable. The production form of the stack
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

> [!IMPORTANT]
> `CreateUser` is only repeatable against a database that has just been
> built. The addresses come from a counter that starts at one every run,
> and a guest may hold ten links per address — so the same addresses,
> reused across runs, exhaust the allowance and the run then measures the
> refusal. Measured: on a database holding 204 186 guest links, 13 299 of
> 20 600 requests came back `429`, and the throughput that produced looked
> like a *result*. Between `CreateUser` points, `docker compose ... down -v`
> and up again — and then `flask db load-base-roles`, or the guest has no
> `link:create` and every request is a `401` instead.

The redirect scenarios need none of that: an address is used once per run
there, and the ceiling is 200 a minute.

### Gunicorn workers

Redirect, 50 concurrent users, milliseconds. Taken twice, once with the
worker count rising and once with it falling, so that a drift over the
series would show as a disagreement between the two:

| `GUNICORN_WORKERS` | req/s | p50 | p95 | p99 |
|---|---|---|---|---|
| 1 | 444 | 100 | 120 | 130 |
| 2 | 761 | 61 | 74 | 100 |
| 4 | 1094 | 43 | 51 | 57 |
| 8 | 1375 | 34 | 43 | 54 |
| 16 | **1523** | 31 | 38 | 42 |

The first series, taken in the opposite order, gave 470, 750, 1176, 1469
and 1524 — no point disagrees by more than 7%. The mixed scenario, same 50
users: 2 → 482 and 447 req/s, 4 → 762 and 715, 8 → 1109 and 1044.

**What follows.** Recording a visit costs a third of the redirect path on
one worker — 743 before, 444 and 470 after — and almost nothing on eight:
1519 before, 1375 and 1469 after. The write waits on the database, and
waiting is what more processes overlap; the machine's ceiling is where it
was.

What did change is the shape at the top. The first run found sixteen
workers worse than eight on both throughput and tail, and that is no longer
so: sixteen leads on both, and the two series agree on it. Both runs still
refuse the old "2 × cores + 1", which would have given twenty-one — but the
knee is now at or past the number of cores rather than below it.

The default stays **4**: it yields 72% of this machine's ceiling, keeps p99
under 60 ms, and stays sensible on a two-core box, which is what a default
is for.

### Connection pool

Link creation, 4 workers, 50 users, on a database rebuilt before each point;
the last column is how many connections PostgreSQL counted:

| `DATABASE_POOL_SIZE` | req/s | p50 | p99 | connections |
|---|---|---|---|---|
| 1 | 622 | 75 | 98 | 5 |
| 2 | 627 | 75 | 90 | 5 |
| 5 | 615 | 76 | 99 | 5 |
| 20 | 617 | 76 | 94 | 5 |

Both ends were taken a second time and landed on the same number, 629 each.
On the redirect path the same flatness: 1142, 1139 and 1138 req/s at pool 1,
5 and 20.

**What follows.** Pool size decides nothing here, and the reason is the
worker class: `sync` carries one request at a time, so a process holds one
connection however many it is allowed. The pool is a ceiling, not a
reserve, and the ceiling was never reached — the connection count says so
outright: five, whether the pool allows one or twenty, which is one per
worker and one for the beat.

The value was lowered from 20 to 5 (and `DATABASE_MAX_OVERFLOW` from 10 to
5) not for speed but because the ceiling multiplies by the number of
workers: 20 + 10 across eight processes is 240 connections against the
hundred PostgreSQL allows by default. Five per process across four workers
is forty, with room either way.

### Cache

Redirect, 4 workers:

| `CACHE_ENABLED` | req/s | p50 | p95 | p99 |
|---|---|---|---|---|
| `true` | 1128 | 42 | 50 | 56 |
| `false` | 823 | 58 | 67 | 75 |

Each row was taken twice, alternating, and repeated within 1%. The cache is
worth 37% of the hot path's throughput — which is why
`CACHE_LINK_TTL` and `CACHE_STATS_TTL` deserve non-zero values. The
particular 3600 and 300 are a freshness-versus-hit-rate choice rather than a
performance one, and this run does not measure them.

### What saturates first

The first two runs measured where the service stops; this one, taken
2026-08-20 on the same machine at sixteen workers, measures what stops it.
An idle percentage says who is busy, not who is holding the line, so each
resource was capped in turn and the ceiling watched for movement. The caps
are `deploy.resources.limits.cpus` in a second compose file passed after
this one, so a point costs no edit to anything the repository keeps.

| what was capped | req/s | p50 | p95 | p99 |
|---|---|---|---|---|
| nothing | **1465** / 1445 | 32 | 40 | 50 |
| Redis cache at 0.25 cores | 1465 / 1432 | 32 | 40 | 48 |
| PostgreSQL at 0.5 cores | 1463 / 1421 | 32 | 40 | 47 |
| the application at 6 cores | 1429 | 33 | 39 | 45 |
| the application at 4 cores | 1414 | 33 | 44 | 52 |
| the application at 2 cores | **729** / 701 | 77 | 94 | 100 |
| Celery worker stopped | **1625** / 1613 | 29 | 37 | 45 |

Where two numbers are printed the point was taken twice, once early in the
series and once late in the opposite order; no pair disagrees by more than
4%. Every run above answered 0.00% failures, which is what makes the
numbers throughput rather than refusal rate.

**What the rows say.** A quarter of a core for the cache and half a core
for the database — a fortieth and a twentieth of the machine — leave the
ceiling where it was. Neither was holding it. Halving the application's
cores halves the throughput, 729 against 1465, which is what a resource
that holds the line looks like. Above four cores there is almost nothing
left to win — 1414, 1429, 1465 — because four is about all the application
can get while everything else on the machine is running.

**Utilisation says the same thing.** Sampled in the middle of the baseline
run:

| container | CPU | what it is doing there |
|---|---|---|
| `app` | 400% | four cores of gunicorn |
| `celery_worker` | 70% | draining the visit queue |
| `redis` (cache) | 15% | 8 600 commands/s — six a request |
| `redis_broker` | 8% | 14 300 commands/s — ten a task |
| `db` | 9% | all but one or two of its 27 connections idle in `ClientRead` |

The host is 5–8% idle throughout, at 67% user and 27% system. The database
figure is the one to read twice: on a redirect that hits L1 the request
never reaches it, and the only writes are the worker's.

Those command counts are per request, not per second divided by luck.
`INFO commandstats` over one 30-second run, 42 750 requests: the cache
answered exactly 42 982 of each of `get`, `eval`, `expire`, `zcard`,
`zadd` and `zremrangebyscore` — the L1 lookup, and the limiter's
sliding-window script, which runs the other four inside itself. The
broker answered ten commands a task, which is the transaction Celery
wraps each one in.

**How far Redis is from its limit.** The same run: the cache spent 1.67
seconds *executing* commands over 30 seconds and the broker 1.04, so the
two instances together used 9% of one core out of ten. The limiter is the
expensive half — `eval` costs 29.6 µs a call against 2.2 for the
redirect's `get`, three quarters of the cache's time — and it is still not
close to anything. The 15% and 8% in the table are mostly the socket, not
the work.

The application takes whatever frees up. Stop the Celery worker — the
redirects still enqueue, nothing drains — and the container goes from 400%
to 505% and the ceiling from 1465 to 1625.

**About a sixth of the machine measures rather than serves.** On the host,
`com.apple.Virtualization` (the whole stack) holds 615%, but locust holds
84% and Docker's port forwarding another 78%. That is 1.6 cores spent on
generating load and moving it across the VM boundary, so 1500 is a floor
for this service, not a verdict on it. Four locust processes instead of
one gave 1378, not more: the generator was never the limit, it is just
expensive.

**Transport against logic.** A 322-byte static file — no cache, no queue,
no logic — runs at 3144 req/s, p50 14 ms. Turned into machine time per
request that is 318 µs for the transport against 615 µs for a redirect
(worker stopped, so 1625): answering a redirect costs about as much again
as receiving the request did.

**What the logging costs.** Each redirect writes a line to
`application.log` and one to the audit journal, and `LOG_TO_CONSOLE` sends
a copy to Docker's json-file driver:

| | req/s |
|---|---|
| both on (default) | 1465 |
| `LOG_TO_FILE=false` | 1545 |
| `LOG_TO_CONSOLE=false` | 1560 |
| both off | 1579 |

Eight percent for the pair. Worth knowing before blaming the framework,
and not worth turning off.

**Deferring the write earns 17%, it does not cost it.** With
`CELERY_ENABLED=false` the click update runs inside the request through
`NullTaskQueue`, and the ceiling drops to 1215 with p50 at 39 ms. The
queue is not overhead on the hot path; it is what keeps the hot path off
the database.

### The visit queue saturates at half the ceiling

The redirect answers from Redis and enqueues the visit; the worker writes
it. Those two rates are not the same, and the smaller one is reached
first. Taken with `constant_throughput`, 50 users, queue length read at
the 28th second:

| redirects/s | tasks left in the queue |
|---|---|
| 194 | 0 |
| 386 | 0 |
| 579 | 39 |
| 775 | 4 777 |
| 1402 | 42 315, growing by ~1 350/s |

So the worker keeps up to about 600 redirects a second and is behind at
800. At the ceiling the queue grows by about 1 350 a second against
roughly 1 400 arriving, which leaves the worker writing well under a tenth
of what it receives. Nothing is lost — the tasks sit in the broker and
drain afterwards at the rate below, which clears 42 315 of them in about
half a minute — so a spike leaves the counters behind by roughly as long
as the spike itself lasted. What that reassurance does not cover is size:
`redis_broker` holds 256 MB under `noeviction`, which is where a long
enough spike stops being harmless.

The worker is not slow. Given the machine to itself it drains 31 490
tasks in 24 seconds — 1312 a second, and that includes the container
starting. It falls behind under load because sixteen gunicorn processes
take the CPU it needs, which is the same finding as everything above:
this machine runs out of processor, and every part of the service is
competing for the same ten cores.

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
