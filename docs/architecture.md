# Architecture

How the pieces fit and which rules hold the boundaries in place. For *why*
a particular decision went the way it did, see [Decisions](decisions.md).

[All docs](README.md) · [Getting started](getting-started.md) ·
[Development](development.md)

| Section | About |
|---|---|
| [Layers](#layers) | Four layers and which way dependencies point |
| [Project layout](#project-layout) | What lives in each directory |
| [Data flows](#data-flows) | Creating, resolving and deleting a link |
| [Caching](#caching) | Two levels, invalidation, why values are signed |
| [Transactions](#transactions) | Unit of Work, and the one counter that breaks the rule |
| [Security](#security) | Authentication, CSRF, sessions |
| [Authorization](#authorization-rbac) | Roles, privilege escalation, the anonymous ceiling |
| [Observability](#observability) | Logs, failover, health |
| [Extending it](#extending-it) | Where a new use case, endpoint or role goes |

---

## Layers

Clean architecture: dependencies point inward. The domain knows nothing
about the database or about HTTP; infrastructure implements the ports the
application declares.

```mermaid
flowchart TD
    subgraph WEB["Web — HTTP"]
        C[Controllers<br/>API · Auth · Admin · Dashboard]
        M[Middleware<br/>Auth · CSRF · RateLimit · Errors]
        S[Pydantic schemas]
    end

    subgraph APP["Application — scenarios"]
        F[Facades<br/>LinkService · AdminService]
        U[Use cases<br/>Create · Redirect · Delete · Stats]
        P[Ports<br/>Cache · Logger · UoW · Mailer]
        D[DTOs]
    end

    subgraph DOM["Domain — rules"]
        E[Entities<br/>Link · User · Role · Permission]
        V[Value objects<br/>OriginalUrl · ShortCode · Email]
        POL[Policies<br/>CodeGenerator · HashCalculator]
        R[Repository interfaces]
    end

    subgraph INF["Infrastructure — implementations"]
        DB[(PostgreSQL<br/>SQLAlchemy)]
        CACHE[(Redis · InMemory)]
        AUTH[JWT · RBAC]
        DI[DI container]
        Q[Celery]
        CLI[Flask CLI]
    end

    WEB --> APP
    APP --> DOM
    INF -.implements.-> P
    INF -.implements.-> R
    INF --> DOM
```

| Layer | Holds | Rule |
|---|---|---|
| **Domain** | Entities, value objects, policies, repository interfaces | Validation failures are `ValidationError(DomainError)`, never `ValueError`. `Role` is a frozen dataclass; `User` compares by identity |
| **Application** | One use case per scenario, facades, DTOs, ports | Every use case extends `BaseUseCase`; dependencies are declared as `@dataclass` fields |
| **Infrastructure** | Repositories, cache, JWT, RBAC, DI, queue | Implements the ports; translates domain ↔ ORM |
| **Web** | Controllers, middleware, decorators, schemas, templates | Makes no authorization decisions of its own — it asks `AuthorizationService`. The markup does too, through `can(...)`, rather than reading role names |

---

## Project layout

```
src/link_shortener/
├── domain/                    # Rules that depend on nothing
│   ├── entities/              # Link, User, Role, Permission
│   ├── value_objects/         # OriginalUrl, ShortCode, UrlHash, Email, OwnerID
│   ├── repositories/          # Storage interfaces
│   ├── policies/              # Password, privilege, role, guest quota rules
│   └── system_permissions.py
│
├── application/               # Scenarios
│   ├── use_cases/             # links · auth · admin · stats · batch
│   ├── facades/               # One object per area, held by the web layer
│   ├── services/              # Work several use cases share, given their uow
│   ├── dtos/                  # Data transfer objects
│   └── ports/                 # Infrastructure abstractions
│
├── infrastructure/            # Implementations
│   ├── database/              # Models, repositories, Unit of Work
│   ├── cache/                 # Redis, in-memory, null
│   ├── auth/                  # JWT and RBAC
│   ├── di/                    # Container and its components
│   ├── configs/               # Configuration profiles
│   ├── cli/                   # Flask commands
│   ├── logging/ · failover/   # structlog, standard, switching between them
│   ├── rate_limit/ · mail/ · task_queue/ · health/
│
└── web/                       # HTTP
    ├── controllers/ · middleware/ · schemas/
    ├── security/              # Decorators, request context, can() for templates
    ├── templates/             # Jinja2
    └── static/                # CSS and page scripts
```

Outside `src/`:

```
dockers/            # Dockerfile, docker-compose*.yml, entrypoint.sh
datas/              # Everything a run leaves behind
├── databases/      #   SQLite files
└── logs/           #   journals, when LOG_TO_FILE=true
migrations/         # Alembic revisions
```

Both `datas/` directories are created on demand and ship empty in git, so
the place is visible from the tree rather than only from the docs. Where
they point is configurable — see [`DATABASE_DIR` and
`LOG_DIR`](configuration.md#storage-locations).

---

## Data flows

### Creating a link

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant A as ApiController
    participant U as CreateShortLinkUseCase
    participant H as HashCalculator
    participant K as Cache
    participant DB as PostgreSQL
    participant G as CodeGenerator

    C->>A: POST /api/v1/shorten
    A->>U: execute(url, context)
    U->>H: hash(url)
    U->>K: get_by_hash(hash, scope)
    alt claim from cache
        K-->>U: code
        U->>DB: confirm the link is alive
    else miss
        U->>DB: find_live_by_hash(hash, scope)
    end
    alt found
        U-->>A: 200, is_new=false
    else
        U->>G: generate(url, attempt)
        U->>DB: save(link)
        U->>K: save(link)
        U-->>A: 201, is_new=true
    end
```

**Deduplication is per owner and only over live links.** The key is the pair
*URL hash + owner*: a registered account is a scope of its own, a guest is
scoped by its `guest_identifier`, and links with neither — the ones the CLI
makes — share the anonymous scope.

Two consequences follow:

- **There is no unique index on `urls.url_hash`.** The same URL legitimately
  appears for different owners, and after expiry for the same one twice. The
  baseline creates the non-unique `ix_urls_url_hash_owner_id` and
  `ix_urls_url_hash_guest_identifier`.
- **A cache hit on a hash is a claim, not an answer.** The code is confirmed
  against the database before being handed back as existing: the `code:` and
  `hash:` keys are evicted independently under `allkeys-lru`, so the entry
  outlives the row it describes.

Expired links take no part in deduplication: otherwise shortening again
would hand back a dead code, and a working link for that URL could never be
created.

### Resolving — the hot path

```mermaid
flowchart LR
    R[GET /code] --> L1{L1 RedirectCache<br/>code → address}
    L1 -->|hit| OUT[302 to the destination]
    L1 -->|miss| L2{L2 LinkCache<br/>code → Link}
    L2 -->|hit| FILL1[Fill L1] --> OUT
    L2 -->|miss| DB[(PostgreSQL<br/>find_by_code)]
    DB --> FILL2[Fill L2 and L1] --> OUT
    OUT --> Q[[Celery: count the click]]
```

The click counter is updated by a task rather than in the request handler.
With `CELERY_ENABLED=false` the same work runs synchronously.

### Deleting

```mermaid
flowchart TD
    K[DELETE /api/v1/links/code] --> UC[DeleteLinkUseCase]
    UC --> T[Transaction: read the row,<br/>decide ownership, delete]
    T --> N{rows deleted}
    N -->|1| INV[Drop every cache entry for the link]
    N -->|0| F[404: another caller took the row]
    INV --> AUD[Audit: link deleted]
    AUD --> OK[200]
```

Ownership is decided by the use case from the row it read in its own
transaction. The answer is built from the number of rows deleted rather than
from a preceding read: under READ COMMITTED two concurrent deletes each see
the row in their own snapshot.

---

## Caching

Two levels, both optional: `CACHE_ENABLED=false` turns every call into a
no-op.

| Level | Key → value | For |
|---|---|---|
| **L1 `RedirectCache`** | `code → destination` | Redirecting without building an entity |
| **L2 `LinkCache`** | `code → Link` | Link information and deduplication |

What the cache is worth, measured: [Development](development.md#load-profile).

### Invalidation

| Event | What is dropped |
|---|---|
| TTL expiry | Automatic |
| Deleting a link | Every key of that link. `Cache.delete(link)` takes the entity, not the code — the deduplication entry is keyed by hash and scope |
| Creating, deleting, clearing expired | The service statistics entry |
| A click | Nothing. Clicks arrive on every redirect, and dropping the entry on each would leave the cache nothing to answer with |

The click counter therefore lags by `CACHE_STATS_TTL`, which is the price
the cache exists for. Invalidation failures are logged and do not abort the
operation.

> [!WARNING]
> **That table describes one process.** With `REDIS_ENABLED=false` the two
> levels live in the memory of whichever process holds them, so an
> invalidation reaches only the process that performed it — which is what
> the startup line `Redis is off, using the in-memory cache; entries are
> not shared between workers` is about, and it applies to the CLI as much
> as to a second worker.
>
> Measured on the arrangement the local profile ships: a link created and
> followed over HTTP, then `flask link delete <code>` in a terminal. The
> command answered `Link '<code>' has been deleted` and the row was gone —
> `GET /api/v1/links/<code>` answered `404` — while `GET /<code>` on the
> running server went on answering `302` to the original destination for
> six minutes and two `cache clear` runs, out of its own cache.
>
> **What closes it, and what it leaves.** Counting a click is the one thing
> that always asks the database, and it now drops both levels for a code
> whose row is not there to increment. So the serving process learns of the
> deletion on the first redirect after it and answers `404` from the second
> on. One stale redirect remains, and is unavoidable: nothing about that
> request reaches the database before the answer goes out, which is what
> the L1 cache is for. It is also written to the audit journal as a
> `URL_ACCESSED`, which is true — the service did redirect.
>
> Rows 1, 2 and 4 of [the arrangement
> table](getting-started.md#choosing-where-each-part-runs) never had this:
> Redis is one cache and every process invalidates in it. Measured on row
> 2 — application on the host, services in containers: a `flask link
> delete` at a shell left **zero** stale answers, the very next redirect
> was `404`, and a link created at a shell was served from the first
> request. Where the cache is in the process, `CACHE_ENABLED=false`
> removes even the one stale redirect.
>
> **What no arrangement notices is a row changed underneath it.** The
> sweep above is triggered by a row that is *gone*; a destination edited
> in the database directly is still a row, so the entry stays and the
> redirect goes on sending people to the old address for as long as
> `CACHE_LINK_TTL` says. Measured on row 2, with Redis: ten redirects over
> five seconds all went to the old destination while `link info` — which
> reads the database — reported the new one, and `flask cache clear` fixed
> it at once because that cache is shared. On rows 3 and 5 the same
> command reaches only its own process, and the wait is the TTL.

### Signed values

Everything the **Redis** cache stores is signed with
`itsdangerous.TimestampSigner` under `SECRET_KEY` — the same library Flask
signs sessions with. The in-process cache signs nothing and needs to: its
entries live in this process's own memory, where anybody able to write to
them can already write anything else.

- **A value is not portable.** The Redis key is used as the salt, so each
  key derives its own signing key. An entry issued for one code does not
  verify under another, and the boundary between key and payload cannot be
  shifted.
- **A value is not eternal.** The issue time is inside the signed message,
  and `max_age` on read rejects anything older than the TTL. This does not
  duplicate the Redis TTL: that one is enforced by the cache server, and
  whoever can write to Redis can set a different one, or none.

Without the signature, a single `SET link_shortener:code:<code> '<valid
JSON>'` is enough to point a redirect at somebody else's address; the
deduplication entry and the statistics go the same way.

A value that fails verification counts as a **miss, not an error**: a miss
sends the request to the levels that can answer, while an exception on the
redirect path would be a 500. An expired signature is rejected exactly like
a forged one.

> [!WARNING]
> Changing `SECRET_KEY` makes the whole cache unverifiable — a deployment
> warms it again from scratch. Every rejection is logged: it is either a key
> rotation or a foreign write into Redis, and an operator should hear about
> both.

---

## Transactions

```python
with self.uow_factory() as uow:
    if uow.links.find_live_by_hash(url_hash, scope) is None:
        uow.links.save(new_link)
    uow.commit()
# Leaving the context without a commit rolls back
```

Reads and writes share one transaction, the commit is explicit, and
anything uncommitted is rolled back on the way out.

> [!WARNING]
> **Counters are not updated this way.** `save` writes the whole aggregate,
> so an entity read earlier and saved back rolls back everything that
> changed in between — the click counter first of all. It has
> `uow.links.increment_clicks(code)`: an atomic `UPDATE` where two
> simultaneous clicks do not read the same number. It returns nothing, on
> purpose: another request may have moved the counter immediately, so an
> entity handed back from there would be a snapshot passed off as the
> current state.

---

## Security

### Authentication

```mermaid
flowchart LR
    B[Browser] -->|HttpOnly cookie<br/>access_token| MW[AuthenticationMiddleware]
    P[Programmatic client] -->|Authorization: Bearer| MW
    MW --> V{Token check}
    V -->|type ≠ access| X[401]
    V -->|sid revoked| X
    V -->|is_active = false| X
    V -->|ok| G[g.current_user]
```

- The JWT carries a `type` claim (`access` / `refresh`), and the middleware
  accepts **only** an access token; a refresh token is good for
  `/auth/refresh` and nothing else.
- An access token carries `sid`, the chain its login belongs to, and that
  is checked on every request. Without it the token would be irrevocable:
  logging out would only delete the client's copy. Measured: on the first
  sign-in `sid` and the refresh token's `jti` are the same value, and they
  part on the first rotation — `jti` names a row, `sid` names the chain
  that row belongs to.
- `is_active` is checked on every request, when an access token is issued
  and at login: deactivation revokes access immediately.
- Cookie lifetimes come from `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` and
  `JWT_REFRESH_TOKEN_EXPIRE_DAYS`, so the cookie and the JWT expire
  together.
- A browser needs cookies specifically: dashboard pages are served by the
  server, and ordinary navigation cannot send a header. Scripts never see
  the token.

### CSRF

Three checks together, on every unsafe method, when the request is
authenticated **by cookie**:

| Check | What it closes |
|---|---|
| **Double submit** | The token in the readable `csrf_token` cookie is echoed in the `X-CSRF-Token` header. A third-party site can make the browser send a cookie; it cannot read one |
| **Signature** | The token is HMAC-SHA256 under `SECRET_KEY`, bound to the user. Without it the scheme accepts any value as long as the two copies match |
| **Origin** | If the browser named an origin, it must be ours. This closes cookie injection from a neighbouring subdomain: cookies do not distinguish subdomains, `Origin` does |

A request with a valid `Authorization: Bearer` does not go through the check
at all: a client that can set a header is not exposed to CSRF. The exemption
is granted on what the request authenticated *with* (`g.auth_token_source`),
not on the shape of the header, and it does not apply to the endpoints in
`COOKIE_AUTHORITY_ENDPOINTS`.

With neither `Origin` nor `Referer` present the origin check is skipped —
proxies strip them — but the signed token must still match.

### Sessions and a stolen refresh token

```mermaid
stateDiagram-v2
    [*] --> Active: login issues<br/>chain_id + jti
    Active --> Rotated: /auth/refresh<br/>old retired, new issued
    Rotated --> Active
    Active --> Revoked: logout
    Rotated --> ChainRevoked: a spent token<br/>is presented
    ChainRevoked --> [*]
    Revoked --> [*]
```

- Every refresh token carries `jti`, the row in `refresh_sessions` it was
  issued as. The chain — one per login, however many times the token
  rotates — is a column of that row, not a claim: measured, a refresh
  token's claims are `email, exp, iat, jti, sub, type` and no more, which
  is why spending one is a lookup rather than a reading.
- Logging out revokes its own session and leaves other devices alone;
  blocking an account revokes all of them.
- Presenting a spent token means a copy exists: **its chain** is revoked,
  not every session the user has, or one dead token would let anyone log a
  person out everywhere on demand.
- Claiming the session during rotation is a single conditional `UPDATE`:
  "read, check, write" lets two simultaneous requests through with the same
  token and produces two live chains, in which thief and owner coexist
  unnoticed.

### The rest

- **X-Forwarded-For** is read only from an address in `TRUSTED_PROXIES`, and
  the rightmost entry is taken — the one the proxy itself appended.
- **The rate limiter** counts by that same `get_client_ip()`, and so do the
  journals: the line opening a request and the audit line beside it name
  one address rather than the proxy and the client.
- **CORS** is confined to the `CORS_ORIGINS` list.

---

## Authorization (RBAC)

| Role | Who that is | Key permissions |
|---|---|---|
| `guest` | An unauthenticated visitor | `link:create`, `stats:view_basic` |
| `user` | A registered account | `link:create`, `link:view_own`, `link:delete_own` |
| `analyst` | An analyst | `stats:view_full`, `stats:view_any`, `link:view_own` |
| `auditor` | Whoever reads the journals | `audit:view`, `logs:view`, `admin:view_system_health`, `stats:view_basic`, `stats:view_full` |
| `admin` | An administrator | `admin:all` |

Roles are seeded from [`configs/rbac/roles.yaml`](../src/link_shortener/infrastructure/configs/rbac/roles.yaml)
and edited afterwards in the panel — the five above are system roles the
service refuses to change, and a role of your own is made from the same
fifteen permissions:

<img src="media/role-permissions.png" alt="The Create Role form: name, description, and the fifteen permissions grouped by what they act on — admin, audit, link, logs and stats" width="820">

### You cannot grant more than you hold

Every path over HTTP by which permissions reach a user checks whether the
caller is entitled to hand them out: assigning roles, creating a user,
creating a role, changing the permissions of one. The CLI is outside that
rule and says so where it is written: a shell already has the database, so
`flask create-user --role admin` is not an escalation it could prevent. A holder of `admin:all` passes
freely.

Without that check, `admin:manage_users` is shorthand for `admin:all`:
assign yourself the `admin` role and read the permissions back.
`admin:manage_roles` does the same in two steps. Both chains fit in one HTTP
request, which makes any "moderator" role a full administrator.

The rule matches the industry one: Kubernetes checks it in the API server
itself and makes the exceptions explicit verbs — `escalate` and `bind`; AWS
IAM solves the same problem with *permissions boundaries*.

> [!NOTE]
> **A cost, accepted knowingly.** A role that is to hand out the `user` role
> must itself carry every permission `user` has. A role holding only
> `admin:manage_users` cannot assign `user` — which is exactly what the rule
> means.

**The last administrator cannot be deleted, deactivated or demoted.** The
check sits on deletion, deactivation and role changes, and counts active
holders of `admin:all` excluding whoever the operation is about. This is
about availability: a system that has lost its last admin is recovered only
from a console.

### The anonymous request and the ceiling over it

A request with no authentication is not "a user without roles" — it is the
`guest` role, which `RBACAuthorizationService` reads from the database.
Anonymous shortening works not because a check is missing but because
`guest` carries `link:create`.

Above the role sits a ceiling in code: `ANONYMOUS_PERMISSION_CEILING` in
`infrastructure/auth/rbac_authorization_service.py`. Whatever the `guest`
row holds, an anonymous caller gets nothing beyond that set.

<details>
<summary>Why a ceiling, when the row is already marked as a system role</summary>

The contents of a role are runtime state, and runtime state can be reached.
On a properly seeded database `guest` is `is_system: true` and the admin API
will not edit it — but that flag is runtime state too: `create_role` sets
`is_system=False` outright, and seeding rewrites scalar fields only under
`update_existing=True`. A `guest` row deleted and recreated through the API
stays unprotected for good.

This class of mistake has been made at every scale. In Kubernetes the
`system:unauthenticated` group is an ordinary RoleBinding subject — that is
what the *RBAC Buster* campaign used — and since 1.28 GKE hard-codes a
refusal to bind `cluster-admin` to `system:anonymous`. PostgreSQL has the
same story with the `PUBLIC` pseudo-role (CVE-2018-1058).

</details>

**If the `guest` row is absent**, an anonymous caller gets nothing: a
missing role means "this deployment did not say what a guest may do", not
"anything the ceiling allows".

### Rate limiting

The numbers live in [Configuration](configuration.md#rate-limits), in one
table generated from `BaseConfig.RATE_LIMITS`. The mechanics:

- The guest quota is counted separately from request frequency:
  `GUEST_LINK_LIMIT` per `GUEST_LINK_WINDOW_DAYS`, per address. What is
  counted is the links that **exist** and were made inside the window, not
  the ones that were made: the query is `count(*) WHERE owner_id IS NULL
  AND guest_identifier = :id AND created_at >= cutoff`, so deleting a link
  frees its place at once — measured, a guest refused at ten was answered
  `201` immediately after removing one with its deletion token. It bounds
  what a guest keeps rather than how often they ask; the throttle below
  is what bounds the asking. An expired link still occupies a place until
  it is deleted or falls out of the window, because it is still a row.
- Counting is per address while the caller is anonymous, and per account the
  moment they sign in.
- `/health` and everything under `/static/` are never throttled: the
  exemption is checked before the limit.
- A `RATE_LIMITS` entry that could never fire is not ignored quietly — the
  application refuses to start. An entry is unreachable when it names an
  exempt endpoint, something under `/static/`, or a name no route answers
  to.
- `RATE_LIMIT_AUTH_DISABLED=true` silences every `auth.*` limit at once and
  does not count as a failure; it is a development switch.

---

## Observability

### Logging

Three parts: the application journal, the audit journal, and failover
between implementations.

```mermaid
flowchart LR
    APP[An application record] --> P{is structlog alive?}
    P -->|yes| S[structlog]
    P -->|no| ST[standard]
    ST -.background check<br/>FAILOVER_CHECK_INTERVAL.-> P
```

Work returns to the primary no more than once every five minutes, and the
cooldown is spent by a check that had something to do — otherwise a service
that is healthy when polled and failing when called would take the work back
on every check.

Work moves down by two routes: an exception from a call, and the health poll
on the background check. The second is needed because the failure the
mechanism exists for raises nothing: a `StandardLogger` with no handlers
answers `is_healthy() == False` and accepts calls in silence.

### Health

`GET /api/v1/admin/health` reports what each dependency answered, and — where
a failover logger is configured — the counters that say whether the audit
trail is still being written. Those counters are reported nowhere else: an
audit trail that had quietly stopped looked, from every surface an operator
has, exactly like one that was fine.

---

## Extending it

| You want to add | Where it goes |
|---|---|
| A scenario | A use case in `application/use_cases/`, extending `BaseUseCase`, with dependencies as dataclass fields; wire it in the DI container |
| An endpoint | A method on a controller in `web/controllers/`, a Pydantic schema for the body, `@require_permission` for the guard — and an entry in `web/schemas/openapi.py`, or the docs test fails |
| A permission | `domain/system_permissions.py`, then the YAML in `infrastructure/configs/rbac/roles.yaml` |
| A role | The same YAML; `flask db load-base-roles` seeds it |
| A storage backend | Implement the repository interface from `domain/repositories/` and register it in the container |

Anything that changes what a page offers a role belongs in the markup's
`can(...)` rather than in a role-name check — see
[Development](development.md#the-frontend-asks-the-server).
