# Decisions

Thirty-one write-ups of why something is the way it is. Read this when the
code does something that looks wrong until you know the reason.

[All docs](README.md) · [Architecture](architecture.md) ·
[Development](development.md)

Each entry has the same shape: **what was decided**, **why**, and — where it
applies — **what was left open**. Dates are when the decision was taken, not
when it was written down.

| Group | |
|---|---|
| [Configuration and profiles](#configuration-and-profiles) | Which database, which secrets, which profile |
| [Database and migrations](#database-and-migrations) | Backends, counters, normalisation |
| [Security](#security) | Passwords, roles, what a refusal reveals |
| [CLI](#cli) | Prompts, exit codes, output that does not lie |
| [Frontend](#frontend) | Navigation, what is vendored, what is prefetched |
| [Known limits](#known-limits) | Things that are wrong and deliberately not fixed |

---

## Configuration and profiles

### Outside `development`, only PostgreSQL

**Decided** (2026-08-11): `production` and `staging` refuse to start on any
backend but PostgreSQL. `development` takes SQLite or PostgreSQL, and a
profile nobody named stays `development` and starts on SQLite.

**Why.** `DATABASE_TYPE` defaults to `sqlite` and `DATABASE_NAME` to
`db_shortener`, so a deployment that forgot to configure a database came up
on an empty new file and answered as though the data had never existed.
Measured: `production` with everything else set passed validation, opened
`sqlite:////<root>/db_shortener`, answered `healthy` on `/health`, and gave
`500 no such table: roles` to the first real request.

The check is on the backend rather than on a forgotten setting because
several roads lead to SQLite and they end the same way: an unnamed file is
created empty; a relative path in `DATABASE_URL` follows the working
directory of the process, and `gunicorn`, `celery` and `flask` do not share
one (measured — the migration wrote 147456 bytes into one file while the
application opened an empty one beside it); an in-memory database under
`SingletonThreadPool` hands every thread its own.

**Left open.** An unnamed profile is not rejected: the `development`
default is the same on a host and in the stack, so the refusal would fall on
a developer who configured nothing on purpose. The consequence is that
`FLASK_ENV` written only in `.env.<profile>` does not select a profile — the
file is read after the choice is made.

### `staging` demands what `production` demands

**Decided** (2026-08-12): `staging` grew its own list of mandatory settings,
including `DOMAIN`.

**Why.** A pre-production environment exists to be wrong in the same ways
production would be. A profile that starts on weaker requirements tests a
configuration nobody will deploy.

### A deployed profile names every fault at once

**Decided** (2026-08-12): `validate()` collects all failures and raises one
error listing them.

**Why.** Stopping at the first means five restarts to learn five missing
variables, each one a build-and-deploy cycle away.

### `DOMAIN` is a host name, not an address

**Decided** (2026-08-12): the value is checked against the two shapes it is
mistakenly given — a scheme in front, and a path behind.

**Why.** `https://short.example.com` produced `https://https://short…` in
every link the service handed out. The check refuses at start-up instead;
the shape of a host name beyond that is DNS's business, not the
application's.

### The database password is optional; the host and the name are not

**Decided** (2026-08-12): `DATABASE_PASSWORD` is no longer required when
assembling a URL from parts.

**Why.** A password is one of several ways PostgreSQL authenticates and the
only one this setting can carry — `peer`, `trust` and `.pgpass` need none.
Requiring it refused configurations that work.

### `postgres://` means PostgreSQL

**Decided** (2026-08-12): the scheme is normalised to
`postgresql+psycopg://` on read.

**Why.** `postgres://` is what managed providers hand out in their console —
and what SQLAlchemy 2 refuses outright. Normalising once, in the one place
every reader goes through, beats explaining the difference in the docs.

### The engine learns the backend from the URL

**Decided** (2026-08-12): the container passes `config.database_backend()`,
which reads the URL, rather than `DATABASE_TYPE`.

**Why.** With an explicit `DATABASE_URL` the parts are not read at all, so
`DATABASE_TYPE` kept saying `sqlite` while the service ran on PostgreSQL —
and the SQLite-only branches (foreign-key enforcement, connect args) were
chosen by that stale value.

### Shared in-memory databases are named through `DATABASE_URL` only

**Decided** (2026-08-11): the `file::memory:?cache=shared&uri=true` form is
supported only as a full URL, not assembled from parts.

**Why.** It is a test fixture, not a deployment. Making it reachable from
`DATABASE_NAME` would put a database that vanishes with the process one typo
away from a production configuration.

---

## Database and migrations

### `increment_clicks` returns nothing

**Decided** (2026-08-12): the repository counts a click with a single
`UPDATE` and hands nothing back.

**Why.** `save` writes the whole aggregate, so an entity read earlier and
saved back rolls the counter back to what it was at read time. The atomic
`UPDATE` avoids that — and returning the row afterwards would hand out a
snapshot as the current state, since another request may have moved the
number in between.

### Email normalisation is computed in Python, not in SQL

**Decided** (2026-08-12): `flask maintenance normalize-emails` decides and
compares in application code.

**Why.** The rule for what an address normalises to already exists in the
domain. Restating it as SQL means two rules that agree until they do not,
and the disagreement surfaces as accounts that cannot log in.

### `normalize-emails` reads the table once and says how it ended

**Decided** (2026-08-12): the command reads the list once, passes it on, and
reports counts.

**Why.** Reading per row turned a maintenance job into a load test on the
database it maintains, and a command that says nothing at the end cannot be
told from one that did nothing.

---

## Security

### Registration does not say whether an address is taken

**Decided** (2026-08-12): the same `202`, the same timing and a message
either way.

**Why.** An endpoint that answers differently for a registered address is an
account enumeration oracle, and this one is public and unauthenticated.
OWASP gives this exact shape for the neighbouring case. The administrative
path (`POST /api/v1/admin/users`) does say outright — there the caller is
entitled to know.

**What it costs.** Somebody registering an address they already own is told
to check their mail and finds a message saying the account exists. That is
the honest form of the trade.

### One address, one account

**Decided** (2026-08-12): addresses are compared in normalised form, and the
uniqueness constraint is on that form.

**Why.** Without it `User@example.com` and `user@example.com` are two
accounts, and which one a password reset reaches is a coin toss.

### A password of invisible characters is refused

**Decided** (2026-08-12): `validate_password` requires at least one visible
character.

**Why.** A password of spaces passes a length check, cannot be typed back
reliably, and is not what anybody meant.

### A role name is bounded by its character set, not only its length

**Decided** (2026-08-12): the name is matched against a pattern.

**Why.** Length alone let through names the delete route cannot address — a
slash in a role name makes `DELETE /api/v1/admin/roles/<name>` point at
something else entirely.

### The anonymous ceiling stands above the `guest` row

**Decided**: whatever the database says about `guest`, an anonymous caller
gets nothing beyond `ANONYMOUS_PERMISSION_CEILING`.

**Why.** The contents of a role are runtime state and can be reached; the
`is_system` flag that protects the row is runtime state too. The same
mistake has been made in Kubernetes (`system:unauthenticated` as an ordinary
RoleBinding subject) and in PostgreSQL (`PUBLIC`, CVE-2018-1058). Full
reasoning: [Architecture](architecture.md#the-anonymous-request-and-the-ceiling-over-it).

### An account's responses are not stored by the browser

**Decided** (2026-08-15): `Cache-Control: no-store` on every response that
belongs to a signed-in caller — `web/middleware/cache_control.py`.

**Why.** Measured, before the header existed: sign in, open the dashboard,
sign out, press Back — and the browser redrew the previous account's
dashboard from its own cache, their address and their links on screen, with
`transferSize` zero and no request reaching the service. The session was
gone (reloading that same URL landed on `/login`), so it was a picture
rather than live data. It was still their picture, on a machine they had
just signed out of.

Neither Turbo's page cache nor bfcache serves that: logging out does a full
load, which discards both. It is the ordinary HTTP cache, and the only
thing that speaks to it is a header on the response that put the page
there. `no-store` rather than `no-cache`, because `no-cache` permits the
browser to keep the entity and revalidate — and history navigation is
exactly the case where it does not revalidate.

Anonymous responses are left cacheable, and so are static files even for a
signed-in visitor: the stylesheet, the font and the vendored navigation
library are the same bytes for everyone and are asked for on every page.
Marking them would re-fetch a quarter of a megabyte per navigation to
protect files handed to anyone who asks.

### You cannot grant more than you hold

**Decided**: every path that hands out permissions checks that the caller
holds them.

**Why.** Without it `admin:manage_users` is shorthand for `admin:all`:
assign yourself `admin`, read the permissions back. Kubernetes checks the
same rule in the API server and makes the exceptions explicit verbs;
AWS IAM does it with permissions boundaries.

### The URL rule is written twice, on purpose

**Decided** (2026-08-10): keep two spellings of one rule — the value object
and the Pydantic schema.

**Why.** They answer different questions at different moments: the schema
refuses malformed input at the edge with a field-level message, the value
object guarantees the invariant for every path that did not come through
HTTP. Collapsing them would mean either a domain that trusts its callers or
an API whose validation errors name no field.

---

## CLI

### `--non-interactive` refuses instead of asking

**Decided** (2026-08-12): `create-admin` prompts in the body of the command,
not through `click.option(prompt=...)`.

**Why.** Declared as a prompting option, `--email` is asked for before the
body runs and before any flag can be consulted — the flag was read by
nothing, and a provisioning script passing it stopped at `Email:` and died
on closed stdin. Which is the one situation it exists to prevent.

### `link create` does not call a deduplicated link created

**Decided** (2026-08-12): the heading of the output depends on `is_new`.

**Why.** A script that reads "Created" and counts links overcounts. The
service already distinguishes the two cases; the command was the only place
that flattened them.

### An empty `--code` is refused, not ignored

**Decided** (2026-08-12): `flask link create --code ""` fails with exit
code 1.

**Why.** An empty string is not "no code given", it is a code that cannot
exist. Treating it as absent silently generates a random one, and the
operator believes they set it.

---

## Frontend

### Navigation is Turbo's, and Turbo is vendored

**Decided** (2026-08-15): `@hotwired/turbo` 8.0.23, copied into
`static/vendor/` and loaded from `<head>`. htmx was the alternative.

**Why.** Turbo merges the `<head>` across navigations; htmx's core replaces
only the `title` and needs the `head-support` extension for the rest. The
layout here is one stylesheet and one script per page, declared in the head
by template blocks, so Turbo understands the pages as they already are.

Vendored rather than served from a CDN because the service runs behind
nothing — gunicorn direct, no nginx, no CDN — and a third-party origin is
one more thing that can be down, be slow, or watch who reads the site. The
package ships no minified build: 212 KB, 45 KB once the compression
middleware has it. `tests/unit/web/test_static/test_vendored_turbo.py` holds
the checksum, which is the only pin a vendored file gets.

**What was left open.** Turbo Frames and Streams are not used. Nothing here
needs to replace part of a page yet.

### Hover prefetch is left on

**Decided** (2026-08-15): Turbo's default prefetch-on-hover stays enabled.

**Why.** Measured on an emulated remote server rather than on loopback,
where the network is free and the question cannot be answered:

| Round trip | Click to painted, prefetch on | off |
|---|---|---|
| 0 ms | 8 ms | 13 ms |
| 60 ms | 8 ms | 75 ms |
| 150 ms | 13 ms | 164 ms |

Without it a navigation costs exactly one round trip; with it the page is
already in hand when the click lands. The cost is smaller than it looks:
Turbo waits 100 ms of hover before fetching and cancels on `mouseleave`, so
a mouse crossing the sidebar on its way elsewhere sent **0** requests, while
pausing on two entries sent 2. One of those costs the server 2.8 ms
(median of 20), and it is a request the visitor was about to make anyway.

The links whose fetch would mean something — the short URLs in the tables —
carry `target="_blank"`, which takes them out of Turbo's hands entirely.
Measured: hovering one sends no request, so the click counter stays honest.

**What was left open.** Prefetches are logged like any other request, and
log rotation does not exist yet. Turbo marks them `X-Sec-Purpose: prefetch`,
so they can be filtered out of the request log if that becomes the reason
the files grow.

### The cached preview of a returning page is turned off

**Decided** (2026-08-15): `<meta name="turbo-cache-control" content="no-preview">`
in the layout.

**Why.** Turbo paints a page you return to twice — the cached snapshot
first, the fresh response second — and re-runs the body scripts on both
renders. Measured on a second visit to `/dashboard/links`: two
`turbo:before-render`/`turbo:render` pairs, one HTML request and **two**
calls to `/api/v1/links/mine`. The visitor sees the previous visit's
figures for a moment before they correct themselves.

With the preview off the same navigation is one render and **one** API
call. It costs little, because hovering a link already fetches the page
before the click lands: the paint that the preview would have saved is a
paint the prefetch has already made unnecessary.

---

## Known limits

Things that are wrong, understood, and deliberately left. Each says what it
would cost to fix.

<details>
<summary><b>Unauthenticated deletion reveals whether a code is taken</b> — accepted 2026-08-10</summary>

`DELETE` on a code that does not exist and on one that belongs to somebody
else answer differently. Aligning them would mean answering `404` to the
owner of a link they may not delete, which is a worse lie than the one this
tells. The redirect and the basic info endpoint answer the same question
publicly anyway.

</details>

<details>
<summary><b><code>mask_url</code> leaves three things unmasked</b> — accepted 2026-08-09 and 2026-08-10</summary>

The masking pattern removes userinfo from an address of the ordinary shape.
It does not touch credentials in an address without `://`, a nested address
in percent-encoding, or a token in a query string.

Extending the pattern to arbitrary text would cost false positives on every
ordinary URL, and the third case is not maskable in principle — a query
parameter is not distinguishable from a secret by shape. What was done
instead: the boundary is stated here and pinned by tests, so the pattern
cannot quietly start claiming more than it does.

</details>

<details>
<summary><b>The background check holds a lock across the health probe</b> — accepted 2026-08-10</summary>

`FailoverService` holds its lock while probing the primary, so a slow probe
blocks the callers that would have used the fallback. The fix is a probe
outside the lock with a compare-and-set afterwards; the cost is a window in
which two probes run at once. Left as is because the probe has a timeout and
the window is bounded by it.

</details>

<details>
<summary><b><code>ALL_SERVICES_FAILED</code> is looked at by nobody</b> — accepted 2026-08-10</summary>

The state exists and is set correctly; no caller branches on it. Removing it
would lose the distinction between "everything is down" and "the primary is
down", which the health report may want later. It is counted, not acted on.

</details>

<details>
<summary><b>The failover service's own logging failure is counted, not retold</b> — accepted 2026-08-12</summary>

When the failover machinery cannot log its own state change, it increments a
counter rather than raising. Raising would take down the request that
happened to be in flight — a request that has nothing to do with logging.
The counter is reported by `/api/v1/admin/health`, which is the only place
an operator can see it.

</details>

<details>
<summary><b>Suite debts: a thread, a mutation and dead imports</b> — accepted 2026-08-12</summary>

Three known imperfections in the tests themselves: the `alembic` group fails
when threading is disabled, one test mutates module state and restores it in
a `finally` rather than through a fixture, and a handful of imports exist
only to be patched. Each is a paragraph of work and none affects what the
suite proves; they are written down so that finding one does not read as a
discovery.

</details>

---

## How to add an entry here

When a decision is made that a reader would otherwise question, add a
section with the same three parts. The value is not the decision — it is the
measurement behind it. An entry that says "we chose X because it is better"
is worse than no entry: it looks like reasoning and carries none.
