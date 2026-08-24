# Decisions

Fifty-one write-ups of why something is the way it is. Read this when the
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
| [Logging](#logging) | Who rotates the journals, and what the choice costs |
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

### The worker count and the pool size were measured, not guessed

**Decided** (2026-08-19): `GUNICORN_WORKERS` defaults to 4 and
`DATABASE_POOL_SIZE` to 5, and both numbers come from a run against the
production form of the stack rather than from a rule of thumb. The tables
are in [Development → Load profile](development.md).

**Why.** `tests/load/locustfile.py` existed for weeks without being run
against anything, and several numbers in this documentation are stated per
redirect and extrapolated per second — 473 bytes of audit a redirect, 389
MB a day at ten a second. What the service sustains was an assumption
holding up those sentences. It is now measured: about 1500 redirects a
second on ten cores, which puts 389 MB a day at roughly 0.7% of the
ceiling.

The run was made twice, in opposite orders, because a series drifts: a
point taken late sits on a fuller database than one taken early. No point
disagrees with its twin by more than 7%, which is what makes the shape of
the curve — not any single number — the thing to read off it.

Three things the measurement changed. Recording a visit costs a third of
the redirect path on one worker and almost nothing on eight, because the
write waits on the database and waiting is what more processes overlap.
Sixteen workers are no longer worse than eight — the first run found them
worse on both throughput and tail, and after the write they lead on both.
And the pool decides nothing at all: 622, 627, 615 and 617 req/s at pool 1,
2, 5 and 20, with PostgreSQL counting five connections in every case, one
per worker and one for the beat. `sync` carries one request at a time, so a
process holds one connection however many it is allowed.

**What it flattens against** (measured 2026-08-20, same machine, same
profile, sixteen workers). The CPU, and not by a small margin. The method
is to take a resource away rather than to read its idle percentage: a
percentage says who is busy, a cap says who was holding the line. Capping
the Redis cache at a quarter of a core moves the ceiling by 0.0% and
capping PostgreSQL at half a core by 0.2%; capping the application at two
cores halves it, 729 against 1465. Utilisation agrees — under load the
database burns 9% of one core with all but one or two of its 27
connections idle in `ClientRead`, and the two Redis instances spend 9% of
a single core between them actually running commands — 1.67 and 1.04
seconds of it over a 30-second run, six commands a request and ten a
task. The host is 5-8% idle throughout. The application takes four cores
and takes more the moment any frees: stop the Celery worker and it goes to
505% and the ceiling to 1625. The tables are in
[Development → Load profile](development.md).

That is the answer to the question, and two things stand beside it that
the ceiling on its own does not say.

**About a sixth of this machine measures rather than serves.** locust
holds 84% of a core and Docker's port forwarding another 78% — 1.6 cores
spent generating the load and carrying it across the VM boundary. So 1500
is a floor for the service rather than a verdict on it, and a generator on
another machine would move it. Four locust processes instead of one gave
1378 and not more, so the generator was never the limit; it is only
expensive.

**The visit queue saturates at half the ceiling.** A redirect answers from
Redis and enqueues the visit; the Celery worker writes it, and that second
rate is the smaller one. The worker keeps up to about 600 redirects a
second, is behind at 800 (4 777 tasks outstanding after 28 seconds), and
at the ceiling the queue grows by about 1 350 a second against 1 400
arriving — the worker writes well under a tenth of them. Nothing is lost:
the tasks wait in the broker and drain afterwards at 1312 a second, so the
counters are behind by about as long as the spike lasted. But "1500
redirects a second" is then a statement about answering, not about
counting.
The broker holds 256 MB under `noeviction`, which is where a long enough
spike stops being harmless.

**What is still open.** The ceiling is one machine's, and this machine
spends part of itself on the measurement. The `CreateUser` scenario is
only repeatable against a freshly built database — the guest allowance is
ten links per address and the profile reuses its addresses — which is
written where the run is described rather than here, because it is a
property of the profile.

---

## Database and migrations

### One revision, edited in place

**Decided** (2026-08-07, written down 2026-08-19): the repository keeps a
single Alembic revision. A change to the models is edited into that
baseline; a second revision is not added.

**Why.** Nothing is deployed from this repository yet, and until something
is, a chain of revisions records the history of a schema nobody ran. One
baseline is read as the schema, which is what a reader wants from it, and
`tests/integration/infrastructure/database/test_migrations.py` can then
assert what a fresh database actually contains rather than what a sequence
of edits ought to have produced.

**What it costs, and it is not free.** A database created by an older
baseline is not caught up: the revision is already applied under the same
id, so `upgrade head` does nothing and the missing column stays missing.
Recreating the database is the ordinary answer, and that is only ordinary
while there is no production data. Measured on a database built before
`security_events` existed: the application starts, the event goes to the
audit journal, the counter logs a warning and the request is answered --
the failure is contained, but the table is still not there.

**When it stops holding.** The first deployment somebody else runs. From
then on the baseline is history and a change is a new revision, because a
revision already applied elsewhere cannot be edited.

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

### A password change takes the current password and closes every session

**Decided** (2026-08-20): `POST /api/v1/auth/change-password` requires
`current_password`, revokes every refresh session the account holds — the
caller's included — and only then opens a new one, handed back in the same
answer.

**Why the current password.** The route is reached with a session, and a
session is what somebody who borrowed the laptop or landed a script on the
page already holds. Without the check, that is enough to change the
password, which locks the owner out of their own account: the one move that
turns a borrowed session into a taken one. ASVS 2.1.5 asks for it by name,
and the cost is one bcrypt comparison on a route nobody calls twice.

**Why every session, and why in that order.** A password is usually changed
because somebody else may know the old one, and a change that leaves their
device signed in has not done the thing it was for. Measured on the live
run: the second device's access token — still a validly signed claim —
answers `401` after the change, and its refresh token answers `401` too.

The order is the part that is easy to get wrong and invisible afterwards.
Opened first, the new session is one of the sessions the next line revokes,
and the caller is signed out by their own change; the end state looks the
same either way, which is why
`tests/unit/application/test_use_cases/test_password_change_closes_every_session.py`
asserts the call order rather than the outcome. Measured by writing it the
wrong way round: one test of the nine reddens, and it is that one.

**Why the answer carries a new pair.** The browser authenticates by cookie,
and the cookie names a session this request has just revoked. Without the
replacement the page that made the change is signed out by it — which reads
to the person in front of it as the change having failed.

**Why the page asks for no permission.** What is on `/dashboard/security`
belongs to the account reading it. There is no permission that could open
or close it: every account that can sign in may change its own password,
and none may change another's from there. The operator's path
(`flask security reset-password`) still exists for the account that cannot
sign in at all.

**Where the rule lives** (2026-08-21). Retiring the sessions and the
mailed links is done by `UserManagementService.update_password`, not by
the use cases above it. There are three callers — the page, the reset
link, and the command — and stated in the callers the rule held in two:
the command replaced the hash and left every session live and every
mailed link working. That is the path reached for an account believed
compromised, so what it left behind was exactly what it was run to take
away. The command now says how many sessions it closed, because "reset
successfully" reads the same whether it closed one or none.

**What was left open.** Recovery by email. An account whose password is
forgotten still needs an operator, and that is the other half of this
feature rather than a decision against it.

### A reset link lives in a table of its own, for an hour

**Decided** (2026-08-20): `password_resets` is a second table beside
`email_verifications` rather than the same table with a `purpose` column.
`PASSWORD_RESET_TTL_MINUTES` defaults to 60. A new request retires the
links outstanding, and so does any password change.

**Why a second table.** The two rows carry identical columns and buy
different things: a confirmation proves a mailbox is readable, a reset
opens the account. Behind one column they are told apart by a `WHERE` in
every query that touches them — `claim`, `invalidate_for_user`,
`delete_expired` — and the one place that clause is left off is a place
where a confirmation link is accepted as a reset link. That is an account
taken over by following a link its owner asked for, from a diff that looks
like a missing filter. Two tables cannot be confused by omission: the
query names one of them. The cost is about two hundred lines of repeated
shape, and the token itself is not repeated — `issue_token` and
`token_digest` were already shared.

**Why an hour, in minutes.** OWASP's Forgot Password Cheat Sheet asks for
"a short expiration time" and names 20 minutes to an hour. The confirmation
token gets 24 hours because losing it costs somebody a second registration
message; this one is a working credential sitting in a mailbox, and the
unit is minutes so that the sentence in the message says so — a reader told
"1 hour" comes back to it in the evening.

**Why a new request retires the old links rather than being refused.**
Refusing while an earlier link lives sounds safer and hands a stranger a
denial of service: anyone who asks for a reset on your address blocks your
own request for the rest of the hour. Retiring instead means the newest
link is the only working one, which is the property that actually matters.

**Why a password change retires them too.** The likeliest reason somebody
changes their password in a hurry is that a reset they did not ask for
turned up in their mailbox. A link that outlives the change is that
stranger still holding the account. Measured by removing that one line:
`test_password_reset.py::test_a_link_mailed_before_the_change_stops_working`
turns red and nothing else in the suite moves.

**Who gets nothing, and one case that is not obvious.** No account, and a
deactivated one — neither can sign in, so a new password buys nothing. And
an **unconfirmed** address: this service has no evidence that mailbox
belongs to whoever typed it into the registration form, so mailing a way
into the account there means mailing it on a stranger's word. That account
already has a road, and it is the confirmation message. All four answer
`202` with one sentence.

**Nobody is signed in by a reset.** OWASP asks for it, and the order is the
honest one: the account has just been opened by a link out of a mailbox,
so the first thing it should ask for is the credential.

**What was left open.** The timing is not level. The branch with something
to do issues a token and commits, so a registered, confirmed address takes
measurably longer than an unknown one — the same leak the confirmation
resend has, and recorded with it under [Known limits](#known-limits).

### A role name is bounded by its character set, not only its length

**Decided** (2026-08-12): the name is matched against a pattern.

**Why.** Length alone let through names the delete route cannot address — a
slash in a role name makes `DELETE /api/v1/admin/roles/<name>` point at
something else entirely.

**Where it is asked** (2026-08-21): in the domain, as
`require_valid_role_name`, and in the YAML loader that seeds roles. The
pattern lived in the Pydantic schema alone, which is the boundary the API
enters through and not the one every path enters through: `flask
db load-base-roles` reads a file an operator edits, and a role named there
with a slash in it was created without anything objecting.

### The anonymous ceiling stands above the `guest` row

**Decided**: whatever the database says about `guest`, an anonymous caller
gets nothing beyond `ANONYMOUS_PERMISSION_CEILING`.

**Why.** The contents of a role are runtime state and can be reached; the
`is_system` flag that protects the row is runtime state too. The same
mistake has been made in Kubernetes (`system:unauthenticated` as an ordinary
RoleBinding subject) and in PostgreSQL (`PUBLIC`, CVE-2018-1058). Full
reasoning: [Architecture](architecture.md#the-anonymous-request-and-the-ceiling-over-it).

### One link's traffic belongs to whoever owns the link

**Decided** (2026-08-19): `?code=` on `/api/v1/stats/visits` and
`/api/v1/stats/visits/daily` is checked against `can_view_link_details`,
the same gate the extended link endpoint uses.

**Why.** Both endpoints answer the service-wide question to a holder of
`stats:view_basic`, which the `guest` role carries — that is deliberate,
because the service-wide answer is a count nobody owns. A named code is not
that answer, and it is not opened by that permission either: see *Your own
statistics are opened by `link:view_own`*, where the three questions behind
this one address are separated. Measured against the running
stack: an anonymous caller who knew a seven-character code was given the
link's total, its bucketed timeline and its device and browser split,
while the same caller asking `/api/v1/links/<code>` got `clicks: null` and
asking `/api/v1/links/<code>/extended` got `401`. Three endpoints, one
question, two answers.

The ownership check only ran when `scope=mine` set an `owner_id`, so the
parameter that names somebody else's link was the one path through these
endpoints with no check on it at all.

**What it costs.** A code that no link carries now answers `404` rather
than a span of zeroes, for everybody. The existence of a code is public
anyway — the redirect and the basic endpoint answer it — and it is only
the traffic behind it that is not.

### Your own statistics are opened by `link:view_own`

**Decided** (2026-08-22): `/api/v1/stats/visits` and
`/api/v1/stats/visits/daily` take either permission at the door and pick
the one the request needs inside — `stats:view_basic` for the
service-wide count, `link:view_own` for `scope=mine`.

**Why.** They held `stats:view_basic` alone, so seeing one's own traffic
depended on holding the permission for the *service's* — whose own
description is "basic service statistics". Everything else about an
account's own material is behind `link:view_own`: `/links/mine`,
`/stats/mine`, and the dashboard page these very charts are drawn on. The
page said so in three places and the route did the opposite. Measured
against the running stack: a role holding `link:view_own` and not
`stats:view_basic` opened `/dashboard/stats` with 200, was served its
tiles by `/stats/mine` with 200, and got 403 from both charts on the same
screen — the empty screen the comment above those page routes promises
not to serve.

**Why a decorator and a check rather than one or the other.** The answer
depends on what the request asked for, and `?scope=` is not something a
decorator can read. `require_any_permission` lets a holder of either
through — which is what decides whether the address is worth opening at
all — and `_require` inside names the one this request actually needed,
so the refusal carries it into the audit journal. The journal page is
built the same way: one permission opens it, and each panel's endpoint
enforces its own.

**A named `?code=` is a third question, with a third door.** It is checked
against that link's owner by `require_can_view_link_details` — the gate in
*One link's traffic belongs to whoever owns the link* — and needs neither of
the other two on top. Requiring the service-wide permission for it as well
shut a holder of `stats:view_any` out of the page written for exactly that
holder: measured on a role carrying `link:view_own` and `stats:view_any`,
`/dashboard/links/<code>/stats` answered 200 and both charts on it 403. The
same shape of defect this entry opened with, one door over, and it was this
entry's own fix that made it — found by walking the perimeter again
afterwards rather than by any test.

**What it costs.** A caller holding `stats:view_basic` and not
`link:view_own` can no longer ask for `scope=mine`. No seeded role is in
that position — `user` and `analyst` carry both — which is exactly why
every branch is asserted rather than left true by accident.

---

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

### The browser is told what it may do with the page

**Decided** (2026-08-19): every response carries `X-Content-Type-Options`,
`X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy` and a
`Content-Security-Policy` whose `script-src` admits one inline block by a
per-response nonce.

**Why at all.** None of them was sent, so each of those decisions was left
to the browser's default — whether to guess a body's type against its
declared one, whether another site may frame this one, and how much of the
address to hand to whatever an outbound link leads to. A short link's own
page carries its code in the address, which is the one that matters here.

**Why a nonce and not `'unsafe-inline'`.** The application serves one
inline `<script>`, the JSON block carrying the translated strings. Excusing
it with `'unsafe-inline'` excuses every injected script along with it, which
is the same as having no `script-src` at all. The nonce is 128 bits from
`secrets.token_urlsafe`, minted in `before_request` so the markup and the
header cannot disagree — a page whose nonce the header does not name is a
page whose script is refused silently, in the browser and nowhere else.

**What `style-src` keeps, and why.** `'unsafe-inline'`, alone among the
directives. The charts position a tooltip, size a bar and colour a swatch
by assigning to `element.style`, which Chromium reports as an inline style
and refuses: measured, the browser run went to 36 failures of 45 and the
console filled with *"Applying inline style violates..."* on every page
that draws anything. Removing it means rewriting how the charts draw, which
is a change to the charts. The narrow half is conceded — an injection that
already runs can restyle the page — and the wide half is not, since
`script-src` is what decides whether it runs.

**What the markup gave up.** The five `style="..."` attributes in the
templates are classes now, including the two that coloured the chart
legend: a refused style attribute renders as an unstyled element rather
than as an error, so the legend would have quietly lost the only thing it
is for.

**What this does not claim.** It does not close cross-site scripting; it
narrows what a successful injection reaches. The consequence that would
hurt most — a script reading the session — was already closed better, by
cookies carrying `httponly`, `secure` and `samesite="Strict"`.

**What it cost the test run.** `browser_test.py` waited on pages with
`page.wait_for_function`, which evaluates a string as JavaScript inside the
page — `script-src` without `'unsafe-eval'` refuses it, and every one of
the fifteen waits died. They poll through Playwright's own protocol now.
Loosening the policy to let the run through was the other way, and it would
have meant the run measuring a policy no deployment would use.

### You cannot grant more than you hold

**Decided**: every path that hands out permissions checks that the caller
holds them.

**Why.** Without it `admin:manage_users` is shorthand for `admin:all`:
assign yourself `admin`, read the permissions back. Kubernetes checks the
same rule in the API server and makes the exceptions explicit verbs;
AWS IAM does it with permissions boundaries.

### No account wears `guest`

**Decided** (2026-08-21): `guest` is the role an unauthenticated request
acts under, so an account wearing it holds what a passer-by holds. The rule
is asked by `User.create`, where an account first gets roles whichever path
built it, and by `UserManagementService.update_roles`, which is the one
path around the factory.

**Why not in the service alone.** That was the first attempt and it was not
enough: registration builds its `User` itself and never enters the service,
so a deployment with `DEFAULT_ROLE_NAME=guest` registered guests — measured
at 202 with the account holding `guest`. The admin panel had left the role
out of the lists it draws and said why, which left the rule living in the
page that draws the form: `PUT /api/v1/admin/users/<id>/roles` with
`{"roles": ["guest"]}` answered 200 on the running stack.

Registration translates the refusal into its own `REGISTRATION_UNAVAILABLE`
rather than naming the role, because naming it would tell an anonymous
caller which part of the deployment is misconfigured.

### The last administrator cannot be removed through a role either

**Decided** (2026-08-21): the rule stood on the three routes that act on an
account — re-roling it, deactivating it, deleting it — and not on the two
that act on a role. Deleting a role carrying `admin:all`, or replacing what
it grants, takes the permission off every holder at once and left the
service with nobody able to administer it. Both routes now ask
`require_administrator_survives_without` before they write.

**Asked only when it matters.** A replacement that keeps `admin:all` moves
nobody, so the count is taken only when the new set drops it. A system role
is refused whatever the count says, and asking in the other order made one
request answer two ways: `DELETE /api/v1/admin/roles/admin` came back
`ROLE_IS_SYSTEM` while two administrators existed and "this would leave the
system without an administrator" while one did — for a role that is never
deletable either way.

### The set of administrators is locked, not merely counted

**Decided** (2026-08-21): `lock_administrator_set` takes
`pg_advisory_xact_lock` before any count of administrators, the way
`lock_guest_quota` does for the guest allowance.

**Why.** Counting and then writing are two statements with nothing tying
them together. Two administrators demoting each other at the same moment
each read "one other would remain" and each proceeded: measured on the
running stack, first attempt, both answered 200 and nobody was left. A row
lock cannot express it — each request locks the account it is about, and
the two never touch the same row. After the advisory lock the same race
answers 200 and 403 and leaves one administrator standing.

On any engine but PostgreSQL the lock does nothing and the guard is
advisory, which is stated where it is taken rather than assumed.

### What is wrong with the request is answered before who is asking

**Decided** (2026-08-21): on the four administrative routes the order of
refusals is: something wrong with the request, then something wrong with
the caller, then something wrong with the state of the service.

**Why.** The order decides what a caller is told to do about it, and it was
decided by accident. `{"roles": ["guest"]}` aimed at the last administrator
came back "this would leave the system without an administrator", which
reads as "find another administrator and retry" for a request no retry can
satisfy. The same body sent by a caller holding only `admin:manage_users`
came back "You cannot grant permissions you do not hold yourself:
link:create, stats:view_basic", which reads as "obtain those two" — and no
account may wear `guest` either way. A mistyped permission name did the
same on the role routes: `PERMISSIONS_NOT_FOUND` to an administrator and
"You cannot grant permissions you do not hold yourself: link:craete" to a
caller holding only `admin:manage_roles`, sending somebody looking for a
way to obtain a permission that does not exist.

**The one place the order is reversed, and why.** A role or an account that
is not there answers 403 to a caller who may not read it, before it answers
404 — because 404 would disclose that it exists. That is the exception, it
is deliberate, and it is marked where it is made.

### A unique index is translated into the refusal it stands for

**Decided** (2026-08-21): `IntegrityError` on `roles.name` and on
`users.email` is caught at the repository boundary and re-raised as
`RoleAlreadyExistsError` and the existing address refusal.

**Why.** The constraint is the only thing that can answer the question
without a race — a check followed by an insert is two statements — so it
has to be the thing that answers it. Left as an `IntegrityError`, it
reached the error handler as an unhandled exception and became a 500: the
service reported itself broken for a request that was merely refused.

### The JWT carries no `roles` claim

**Decided** (2026-08-21): the access token names the account and nothing
about what it may do.

**Why.** A claim is a snapshot, and permissions are read fresh from the
database on every decision that matters. Carrying both meant carrying two
answers to one question, with the token's answer being the stale one and
the easier one to reach for — the shape of every "the role was removed and
they could still do it" report. Nothing read the claim; it was written,
carried and trusted by nobody, which is the best moment to remove one.

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

### The domain marks its sentences; the boundary translates them

**Decided** (2026-08-16): a domain error carries three things — the finished
English `message`, a `template` with named placeholders, and the `params`
that fill it. `domain/i18n.py` holds `N_`, which returns its argument and
exists only so `pybabel extract` can see the string. Translation happens in
`web/i18n.py:translate_error`, at the boundary.

**Why.** The sentences are written where the failure is understood, which is
the domain — and the domain must not import Flask-Babel: the CLI and the
Celery worker raise the same errors with no request anywhere near them.

Marking rather than a table of `code → sentence` in the web layer, because
`VALIDATION_ERROR` is one code covering 51 different sentences. A table
answers all 51 with one, and "Password must be at least 8 characters" is
exactly the sentence a person needs.

`template` beside `message` rather than instead of it, because an f-string
is finished before anybody can translate it: by the time the boundary sees
`"Link with code (abc123) not found"`, no catalogue entry matches, `gettext`
hands the string straight back, and the page renders in English with nothing
reporting a fault. The English `message` stays because `application.log` and
the CLI read it, and neither has a reader to negotiate a language with.

Placeholders are named, not positional: Russian and Chinese both move the
value inside the sentence, and `%s` cannot be moved past another `%s`.

`N_` needs no extraction flag — it is already in Babel's default keywords.

**What was left open.** `details[].message` stays English: those sentences
are built inside Pydantic from a rule name, so there is no msgid to mark.
Sentences behind a 5xx are deliberately unmarked — the handler answers the
generic one, so marking them would put the service's internals in front of
a translator with no way to see where they appear. The exception is named
rather than implicit: `error_handler.CODES_WORDED_FOR_THE_CLIENT` lists
the 5xx codes whose sentence *is* written for whoever reads it, and holds
one entry. `REGISTRATION_UNAVAILABLE` says a deployment cannot register
anybody, which somebody who just pressed Register is owed in their own
language; it is a code of its own for that reason, because it used to
share `CONFIGURATION_ERROR` with a sentence naming a role from the
configuration, and one code cannot have two audiences.

And a refusal Werkzeug words itself keeps its English. The statuses a
visitor here actually meets have sentences of this project's own — 400,
403, 409, 413, 415 and 503 in `_sentence_for`, 404 and 405 in handlers of
their own, 410 and 401 and the guest ceiling as domain errors, and the
throttle's 429 through `ngettext` — and the web layer calls `abort()`
nowhere, so nothing else is raised from inside it. What is left is the set
this service does not answer with at all: 408, 422, 451, 501, 502, 504 and
their neighbours, which arrive from Werkzeug or a proxy. Their descriptions
are written for a developer rather than for a reader, and translating a
status nobody here raises would mean marking sentences no one can see in
place to check.

### A refusal page decides by code, never by its own wording

**Decided** (2026-08-16): `error.html` is reached through one function,
`web/responses.py:error_page`, which is given the error code and decides
from `CODES_OFFERING_LOOKUP` whether the page offers a lookup form.

**Why.** The page used to test `'link' in error|lower` — twice, once for the
form and once for its script. That works only while the sentence is English:
"Ссылка не найдена" does not contain `link`, so the first translated 404
would have dropped the recovery form from the one page that most needs it,
silently, on a page that still renders perfectly. Nothing measured it —
before this change no test looked at that form at all.

One function rather than the twelve `render_template("error.html", ...)`
calls it replaced: a thirteenth caller forgetting the code costs exactly the
same silent loss, and there is now one place to forget it in.

**What was left open.** The list is two codes, `LINK_NOT_FOUND` and
`LINK_EXPIRED`, which is what the prose test matched in practice.

### A page script is handed its sentences; it never carries them

**Decided** (2026-08-16): the sentences the page scripts write onto a page
live in `web/i18n.py:script_strings`, are translated on the server, and
reach the browser as a `<script type="application/json">` block that
`layout/base.html` prints. A script asks for one by key — `t('no_links_yet')`
— and never holds English of its own. Where the sentence belongs to a control
the server already drew, it goes on that control instead, in `data-confirm`,
already translated and already filled in.

**Why.** A script runs in the browser, where `gettext` has long since had its
turn. A string typed into a `.js` file is therefore in the language it was
typed in, on every page, in every language — the page arrived in Russian and
the script wrote English into it. There were about forty-five such strings,
and sixteen of them were not even quoted sentences: they were text nodes
inside markup being concatenated, `'<span>Clicks</span>'`, which a search for
quoted prose does not find.

In the page rather than fetched from a route of its own: a second request
would arrive after the first "Working…" was already on screen, and it would
need a cache keyed on the language cookie to be worth making.

`application/json` rather than `window.I18N = {...}`. The browser does not
execute the block, so a translated sentence is data and never code — and a
`.po` file is something an operator edits, where a stray quote should cost a
sentence rather than the page.

The keys sit in one Python function rather than in the layout, because the
scripts and the dictionary have to be checked against each other and there is
one list to read. `t()` answers an unknown key with the key itself, so a
rename puts `no_links_yet` on the page where a sentence belongs — ugly on
purpose, an empty string being a page that looks finished and says nothing.

Substitutions are named, `%(code)s`, for the reason the domain's are: a
translator moving the value across the sentence has to know which value it
is.

**What was left open.** The whole dictionary travels with every page, so a
page pays for sentences its own script never asks for. Measured: 1404 bytes
in English, 4257 in Russian — Flask's `tojson` escapes non-ASCII, so every
Cyrillic letter travels as `\uXXXX` — and 594 and 915 bytes respectively once
`web/middleware/compression.py` has had it. Splitting the dictionary per page
would mean each template naming the keys its own script uses, which is the
second list this arrangement exists to avoid.

The strings a script shows are also reachable a second way, from the service
itself: `data.message` on a refusal is already translated by the API, which
answers in the language of the same cookie. The two are not fallbacks for
each other, and `apiErrorText` says so where it picks between them.

### The charts are drawn by hand, and are polled rather than pushed

**Decided** (2026-08-16): `static/js/charts.js`, plain SVG through
`createElementNS`, no charting library. The figures refresh on a timer the
reader chooses — 5 s, 10 s, 30 s, 1 min, 5 min or not at all — and never
over a connection the service holds open.

**Why.** The pushed version is the one to want and the one this deployment
cannot have: production is `gunicorn --worker-class sync --workers 4`, where
every held-open connection occupies a worker for its whole life. Four open
dashboards would be the entire service, and the pages that are not charts
would stop answering. SSE and WebSocket are therefore not a tuning question
here but a change of worker class, which is a decision about the whole
service rather than about a chart.

Polling costs a request per interval and nothing else, and the reader is
given the interval because only the reader knows whether they are watching
a launch or glancing at a week. The off switch is a real position, not a
placebo: it stops the redraw under the pointer as well as the query behind
it, and it is a different control from "Refresh now" beside it, which
fetches once. The two were one control at first and the difference was
invisible — the button said "manual", which promised a field to type an
interval into that does not exist.

The timer is owned by `charts.js`, which is loaded from `<head>`. That is
the whole reason it is not a page script: Turbo re-executes page scripts on
every navigation, so a `setInterval` started by one would outlive the page
that started it — ten navigations, ten timers, all polling for statistics
nobody is looking at. `turbo:before-cache` clears them, and the listener
that does it is registered once per tab because the head is merged rather
than re-run.

**Colour is measured, not chosen.** People and robots are two steps of one
hue, because a robot visit is part of the same count rather than a
neighbouring category. Device classes and browser families get three hues
and a grey "Others", and three is a limit rather than a preference: on the
dark surface every candidate fourth hue collapses into one of the first
three under colour blindness — blue against violet is OKLab ΔE 2.3 where 8
is the floor — and two slices nobody can tell apart are worse than an
honest tail. Red and yellow are excluded on top of that, since in this
system they mean refused and warning.

**What was left open.** Five fixed intervals rather than a field, so the
shortest possible interval stays a decision made here rather than in a text
box. The daily chart is refreshed with the page and by the button, never by
the timer — it answers from a roll-up that gains one row a day.

---

### One link's page asks under its reader's entitlement

**Decided** (2026-08-22): `link_stats.html` sends `scope=service` beside the
code for a holder of `stats:view_any`, and `scope=mine` for everybody else.

**Why.** The tiles at the top of that page come from
`/links/<code>/extended`, which answers the link's owner, an administrator
and a holder of `stats:view_any` — the three named in *One link's traffic
belongs to whoever owns the link*. The charts beneath them were fetched
under `scope=mine` for all three, and the service applies the owner and the
code as one condition, so the third of those three was shown a stranger's
link reporting five visits in the tiles and none in the chart under them.
Measured against the running stack: `/extended` answered `clicks: 5`,
`/stats/visits?scope=mine&code=…` answered `total: 0`, and the same
question without the owner condition answered `5`. The page's own script
said the two halves answered for the same three people, and the controller
behind it said they did not; both are true now.

**The owner condition is not gone, it is scoped.** Every reader without the
entitlement still sends it, which leaves it as a second lock behind
`require_can_view_link_details` on an address that carries a short code —
and short codes are guessable by construction. What it stopped being is the
only thing keeping the page honest: the endpoint refuses a stranger's code
by itself, and has since that entry was written.

**What the controller's docstring claimed.** That a stranger's code
"answers with zeroes rather than with its figures", which stopped being
true the day the guard went in — it answers 403, to the page and to the API
alike. Measured: both halves of the page, 403.

---

### One table of spans, and one place that decides where each begins

**Decided** (2026-08-22): `PERIODS` and `span_of` live in
`application/utils/chart_spans.py`. Both the visit charts and the security
counters import them; neither keeps a copy.

**Why.** They kept a copy each, and a test held the two dictionaries equal.
What that test could see was the names and the widths. What it could not
see was the alignment, which lives in the code that turns a span into two
moments — and there the two had drifted: the counters moved a span drawn in
whole days onto the days themselves, while the visit charts took the last
N days from the instant the question was asked.

Measured at 14:37:05 UTC on 2026-03-10:

```
30d  visits  2026-02-08T14:37:05Z .. 2026-03-10T14:37:05Z
30d  events  2026-02-09T00:00:00Z .. 2026-03-11T00:00:00Z
```

Nine hours and twenty-three minutes apart, on two charts a reader is
invited to compare — which is the thing the shared span table existed to
prevent, and it was the half nobody was comparing that broke it.

**The alignment matters on its own, not only for the comparison.** The two
long spans are drawn in day-wide buckets and their axis is labelled by
`formatDate`, which prints a date and no time. A bucket beginning at 14:37
labelled "8 February" holds an afternoon and the morning after it. It is
also what makes a folded day readable: a total between midnights cannot be
laid on a bucket that straddles two of them, and `link_visit_days` exists
so that the sweep does not take the long-range chart's past with it.

**The short spans are deliberately not aligned.** An hour of a 24-hour span
means the hour that just passed; rounding it to the clock would answer a
different question.

**What holds it now.** The two use cases are asserted to hold the *same
object* rather than equal ones, and the alignment is asserted from three
sides: the helper, each use case, and the endpoint the page fetches.

---

## Logging

### Rotation is somebody else's job

**Decided** (2026-08-16): nothing in `infrastructure/logging` rotates. The
application writes through `RaisingWatchedFileHandler`, which reopens the
file when it is moved aside; the moving is done by logrotate, shipped as
`dockers/logrotate.conf` and run either by the `logrotate` service under
the `logs` profile or by the host's own logrotate.

**Why.** Production is `gunicorn --workers 4 --worker-class sync`, and each
worker builds the application for itself: four processes hold four
descriptors on one `application.log`. A handler that rotates for itself
rotates four times over, and `doRollover` opens the base file in `w` mode —
it truncates a file the other three are writing into.

Measured, four processes writing 20 000 records of 265 bytes each into one
file, rotating every megabyte, with retention off so that a missing record
means a lost one and not a deleted one:

| | records lost of 80 000 | writes that raised |
|---|---|---|
| `RotatingFileHandler` in each process | 8 420 / 8 420 / 12 609 | 12 / 12 / 5 |
| `WatchedFileHandler`, rotation outside | 0 / 0 / 0 | 0 / 0 / 0 |

Three runs each. That is 10.5 to 15.8 per cent of the journal destroyed,
about 470 records per rotation, and the errors are not the quiet kind: this
application re-raises failed writes for its own records, so each one
reaches `FailoverService`, moves the work to the other logger and is
counted in `dropped_calls`. `TimedRotatingFileHandler` is the same race
with four clocks added.

The cost of the arrangement chosen is one `stat` before every write:
`FileHandler` 3.58 µs per record against `WatchedFileHandler` 5.16 µs,
measured over 200 000 records. At three records per request that is five
microseconds a request, against a request measured in milliseconds.

**Retention differs by journal because the journals differ.**
`application.log` and `error.log` are written by traffic — 796 bytes per
request, so 690 MB a day at ten requests a second — and are kept for 14
generations, capped at 100 MB a file.

`audit.log` is written by traffic too, and this entry said otherwise for a
day. It claimed the journal grew "from events, not traffic, 750 bytes
each", and concluded that a year of it compressed to single megabytes and
so needed no size cap at all. Every part of that was wrong.
`log_url_accessed` is called on every redirect, in all three branches of
`redirect_link` — the cache hit, the entity hit and the repository read —
so one line is written per hit and the journal grows exactly as fast as the
service is used.

Measured on this tree, driving real redirects through a real application:

| | claimed | measured |
|---|---|---|
| per event | 750 B | 473 B (344–525, browser agents, four destinations) |
| lines per redirect | — | 1000 per 1000 |
| at 10 redirects/s | — | 389 MB a day |
| live file, weekly rotation | — | 2.7 GB |
| 52 generations, compressed | "single megabytes" | 4.1 GB |
| compression | 23× | 33.8× |

The line has a ceiling and a floor for the same reason: `mask_url`
truncates an address past 100 characters to 73, so a long destination stops
adding bytes, while the user-agent is not truncated by anything and is the
field that actually varies.

So `audit.log` now carries `maxsize 1G` beside `weekly`, and `rotate` rises
from 52 to 200. The two numbers are one decision: a cap alone would have
bought a smaller file by shortening the history, which is the one thing
this journal exists to keep. 200 generations of a gigabyte cover a year
until traffic passes about 14 redirects a second; above that the
generations run out before the year does, and that is the limit of the
arrangement rather than a setting to tune. It costs about 6 GB of disk —
200 compressed generations of some 30 MB — against an uncapped live file
that reaches 13 GB in a week at fifty redirects a second.

**What was left open.** Two things the choice does not cover. The rotation
depends on the profile being named: `.env.example` ships `logs` in
`COMPOSE_PROFILES`, and a deployment that trims that list, or copies an
older file, loses rotation without a word — the service goes on answering
and the files go on growing. Nothing checks that the profile is on, because
a deployment rotating from the host is entitled to have it off. And the
second stream is untouched by any of it: gunicorn's access log goes to
stdout and nowhere else, where the Docker `json-file` driver keeps it with
no limit unless `DOCKER_LOG_MAX_SIZE` and `DOCKER_LOG_MAX_FILE` set one,
which they now do for `app` and `celery_worker` and for nothing else in the
stack.

### The worker logs where the application logs, and does not raise

**Decided** (2026-08-17): the Celery worker configures logging from
`celery.signals.setup_logging`, with the same settings the web process
builds, except that a failed write does not reach the caller.

**Why.** `setup_logging` had one caller, `create_app`, and a worker never
goes through it. Measured before the change, by starting a real worker
against a dead broker with a log directory of its own: three connection
failures reported on stdout, and not one file created. Everything a task
logged — the sending of a message, the failure of one — was outside the
journals entirely, which is where an incident is reconstructed from and
what a journal viewer would read.

Raising is what the two processes cannot share. It exists to feed
`FailoverService`: the service decides to move work by catching an
exception from the call, so a swallowed write failure means no switch and a
silent loss. Nothing plays that part behind the module loggers a task uses,
so the same handler there would turn a full disk into failed work — an
email not sent because a log line could not be written. The setting is on
`LoggingSettings` rather than at the call site, since it is a property of
the process rather than of the deployment.

Connecting a receiver to that signal is also what stops Celery configuring
the root logger its own way; that is the documented meaning of having one,
and it is why this does not fight the worker for the handlers.

**What this costs.** More writers on the same three files: four gunicorn
workers, the worker itself, and its prefork children — ten of them by
default, one per core. That is what the rotation above is built for, and
the reason nothing in either process rotates anything itself.

### A moment is written one way, and the way says which clock

**Decided** (2026-08-17): every journal line states its moment as
`2026-08-17T09:31:43Z` — ISO 8601, UTC, to the second — from one constant,
`UTC_SECONDS` in `infrastructure/logging/utils.py`. `LOG_DATE_FORMAT` no
longer reaches any file; it dresses the console line and stops there.

**Why.** The two chains disagreed. `structlog_config` stamped
`TimeStamper(utc=True)` while `JSONFormatter` took
`datetime.fromtimestamp(record.created)` with no zone, which is the
machine's local one — so on a laptop three hours east of Greenwich the same
second was written `09:31:43` by one configuration and `12:31:43` by the
other, and neither line said which it meant. `MinimalLogger`, which writes
the lines around a logging failure and is read beside both, was local too.

Nothing had ever read a journal back, which is why a fault of this size sat
in a file that four processes write to. It surfaced while measuring
something else.

The format was a setting as well as a zone: `LOG_DATE_FORMAT` was handed to
`JSONFormatter`, so a deployment could set it to anything a person likes
and leave the file unreadable by any program. A journal that will be
filtered by time, ordered against another journal, or shipped to a
collector is read by programs; the console line is read by a person, and
only that line keeps the setting.

Keeping it there took a second fix, on 2026-08-19: `ConsoleFormatter` takes
a `datefmt` and stamps with it, and `bootstrap` built one with no arguments
in both places, so the setting was read from the environment, carried on
`LoggingSettings` and consulted by nothing — whatever a deployment set, the
console showed the formatter's own default. It is now handed the setting on
both consoles the standard chain writes. The structlog chain renders its
console over the one processor chain it shares with the file, so its console
line carries the same ISO stamp the journal does, and that is stated in
`utils.py` rather than left to be found.

**Why to the second and not finer.** That is what both chains already
wrote, and the change is meant to fix the zone rather than quietly raise
the resolution. Ordering within a file is by time of write, not time of
event, so a finer stamp would sharpen a number that was never the
authority on order — and it would cost seven bytes on every line of a
journal this document has just finished measuring.

**A third of the journal had no clock at all**, and only the live stack
said so. `ProcessorFormatter` runs the application's processor chain for
records that came through structlog and hands everything else to the
renderer as it stands — so Celery's lines, werkzeug's and any library's
carried neither `timestamp` nor `level`. Counted on the running stack:
14 lines of 45 in `application.log`, and among them the two Celery writes
that happen on every redirect, `Task received` and `Task succeeded`. The
share therefore grew with traffic rather than being a start-up artefact,
and those are the lines somebody reads when a task has failed.

`FOREIGN_PRE_CHAIN` in `bootstrap.py` gives a foreign record the same three
fields from the same constant. After it, on the same stack driven the same
way: 39 lines of 39 stamped and levelled.

**What holds it.** `TestBothChainsWriteOneClock` in
`tests/integration/infrastructure/test_records_reach_the_journals.py`, in
four parts: each chain's stamp is parsed and bracketed against real UTC
taken around the call, the two chains are compared against each other,
`LOG_DATE_FORMAT` is set to something no parser accepts to prove it reaches
no file, and a record made by `celery.worker` — a logger outside this
application — is asked for its stamp and its level. The first is the one
that matters most: comparing the chains to each other alone would pass on
any machine whose local zone is UTC, which is every CI runner and none of
the laptops the fault was found on.

**What found it.** Not the suite. The zone difference surfaced while
measuring something else, and the missing stamps surfaced only when the
Docker stack was raised and its journals read by eye — the suite had every
opportunity and no reason to look, because nothing in it had ever asked
what a line from another library looks like on disk.

### The journals are shown in the interface, and each one asks for its own permission

**Decided** (2026-08-17): `GET /api/v1/journals/<journal>` serves the last
lines of `application`, `error` or `audit`, and `/dashboard/service/journals`
displays them. The audit journal is read under `audit:view`, the other two
under `logs:view`, and the decision is made in `ReadJournalUseCase` rather
than in a route decorator.

**Why an endpoint at all.** The journals were readable by whoever had a
shell on the host, which is a smaller set than the people who need to read
them and a larger set than the people who should. An auditor with no
deployment access could see nothing; an operator with deployment access
could see everything, including the record kept about their own actions.
The permissions split that in two, and a surface is what makes the split
usable — a permission nobody can exercise without `ssh` is a permission
that gets worked around by handing out `ssh`.

**Why two permissions and not one.** The three journals expose different
things. `audit.log` carries destination addresses and the accounts that
followed them — measured, it is the only one of the three that ever
contains a token, since `mask_url` leaves a token in a query string
untouched. `application.log` carries the email address of everyone who
registered, signed in, or failed to sign in. Google Cloud draws the same
line between `logging.viewer` and `logging.privateLogViewer`. What
`admin:all` does not carry is `audit:view`, for the reason written where
`BEYOND_ADMIN_ALL` is defined: the administrator is the caller the audit
trail is chiefly kept against.

**Why the check is in the use case.** Which permission applies depends on
which journal was asked for, and a decorator is fixed at import time. A
route guarded by one of the two would be a second, coarser answer to the
same question, and the coarser of two answers is the one that eventually
decides. The route therefore carries no `@require_permission`; it converts
the name in the address into a `Journal` member — which is what makes a
path unspellable — and the use case, over `PERMISSION_FOR`, decides. The
dashboard page is the one place with a decorator, `require_any_permission`,
and it guards nothing but whether the page is worth opening: every journal
on it is fetched through the endpoint that checks the permission belonging
to it.

**Polled, like the charts, and for the same reason.** Production is
`gunicorn --worker-class sync --workers 4`. A journal held open over SSE
would occupy a worker for as long as somebody is reading, and four readers
would be the whole service. The same five intervals and the same off switch
the charts offer, because it is the same question asked of a different
reading.

**What is shown.** The fields every record carries — time, level, event —
as columns, everything else as `key=value`, and the raw line one click
underneath: a rendering is a summary, and an operator reconstructing an
incident eventually needs the bytes. A line that is not JSON is shown as it
was found and marked, never dropped; a viewer that silently omits what it
cannot parse is least trustworthy exactly when it matters. Under the table
is what the answer *reached*, as against what exists — without it the
oldest line on screen reads as the beginning of history, when it is usually
the point at which the page filled up.

**Timestamps are not converted.** The journals are stamped in UTC by one
constant, and the page shows that stamp. The reader's own clock is offered
as the cell's tooltip. A page that quietly shifted the times would leave an
operator comparing a screen against a file and finding them three hours
apart.

**What looking at it changed.** Four things, none of which any test had an
opinion about: `Url accessed successfully` wrapped onto two lines while the
column beside it had room to spare; the timestamp was printed twice, once
as written and once in local time, and on a journal every line of which is
the same second that was a third of the table's width; the table scrolled
the whole page, so choosing a different journal meant scrolling back up to
reach the button; and the label read "1 lines from error.log", which is
wrong in English and, at "1 строк", wrong in Russian — the count reaches
the page in the browser where `ngettext` cannot follow it, so the sentence
became a label with a colon, which takes any number in all three languages.

**What the measurement changed.** Making the table scroll inside its own
box introduced a fault and hid another. The heading row scrolled away with
the rows, leaving four unlabelled columns of monospace — fixed by making it
sticky. And the first fix for scroll position restored `scrollTop` after
every poll, which turned out to be a line that did nothing: measured with
it removed, a reader stopped partway is left at 300 before the poll and 300
after, because replacing rows through `innerHTML` leaves the box alone.
What the browser does get wrong is the reader watching the tail — new lines
arrive below them and the box does not follow, and two polls at five
seconds put the tail 204 pixels out of sight. Only that half is code now,
and `browser_test.py` reddens by 1428 pixels without it.

**What was left open.** The reading is not itself recorded. An audit trail
that does not say who read it is half a trail, and the event to write —
`AUDIT_VIEWED` — belongs with the other security events the journal does
not yet carry: `LOGIN_SUCCEEDED`, `LOGIN_FAILED`, `USER_CREATED`,
`ROLES_CHANGED`. They are one piece of work and it is the next one. There
is also no search and no filter: the page answers "what just happened",
and "what happened to this account in March" is a question for the branch
that adds the events worth counting. *Closed by the entry below, except
for the search.*

### The audit journal records what the service does about accounts, and who read it

**Decided** (2026-08-18): the audit journal carried three events — a link
created, followed, deleted — and nothing about accounts at all. It now
carries seventeen more, through one method on `AuditLogger`
(`log_security_event`) and a named wrapper per event above it.

**Which events, by one rule.** An act that changes who may do what leaves a
record. That admits both sign-in outcomes, the five things that happen to
an account (`USER_CREATED`, `USER_DELETED`, `USER_ACTIVATED`,
`USER_DEACTIVATED`, `USER_EMAIL_CONFIRMED`), an address proving itself
(`EMAIL_CONFIRMED`), the roles on an account (`ROLES_CHANGED`), the three
things that happen to a role itself (`ROLE_CREATED`, `ROLE_DELETED`,
`ROLE_PERMISSIONS_CHANGED`), the three ways a password is replaced
(`PASSWORD_CHANGED`, `PASSWORD_RESET`, `USER_PASSWORD_RESET`) and the
reading of a journal (`AUDIT_VIEWED`). It excludes listing accounts,
reading one, and seeding the database: they change nothing, and a journal
that records reads as loudly as writes buries the writes.

`USER_PASSWORD_RESET` is the third one this rule caught late, and the
first caught from the shell rather than from a route. `flask security
reset-password` is the operator's path, reached for an account believed
to be compromised, and it wrote nothing: the account then showed a
password that had changed at a time nothing in the journal accounted for,
which is precisely the shape of the takeover an investigation is opened
over. It is its own event and not a field on `PASSWORD_RESET`, by the
naming the enum already followed — `USER_*` is an operator acting on
somebody else's account, a bare name is the account acting for itself.
Creating an account from the shell was unrecorded for the same reason and
is fixed the same way, by calling the wrapper that already existed
(`USER_CREATED`): the account an operator seeds a deployment with is
typically its only administrator, and it was the one account whose
creation the journal did not hold.

`EMAIL_CONFIRMED` is the second one this rule caught late, and it was
caught by the same reading of it. `USER_EMAIL_CONFIRMED` below is an
operator asserting that an address is readable; this one is the address
proving it, from the link that was mailed there — and it is the act that
turns an account which cannot sign in into one that can. Its two
neighbours on the self-service path, `PASSWORD_CHANGED` and
`PASSWORD_RESET`, were recorded from the start, so the journal for an
account showed it registering and then simply beginning to sign in. The
naming follows what the enum already did without saying so: `USER_*` is
an operator acting on somebody else's account, and a bare name is the
account acting for itself.

`USER_EMAIL_CONFIRMED` is the one this rule caught late. An operator
marking an address confirmed bypasses the proof that anybody can read that
mailbox, and what it hands over is the ability to sign in -- the same kind
of act as suspension and deletion, behind the same permission as both. The
comment in `confirm_user_email.py` explaining why it wrote to the
application log and no further cited an audit port that carried link
events and nothing about accounts; this entry is what made that false, and
the file was never revisited. Measured against the running stack
afterwards: of twelve administrative operations driven by hand, it was the
only one leaving no record. The role events are the ones easiest
to leave out and the worst to be without — changing what a role grants
moves what every holder of it may do, at once, with no account touched, so
an investigator asking why an account could suddenly do something finds
nothing against that account.

**Why not a method per event.** Five events were asked for and eleven were
written, which is the argument by itself: on the port's original shape each
would have cost an abstract method and three adapter implementations — 33
methods to add eleven events. The abstract method is one, the adapters
implement it once each, and the typed wrappers sit in the ABC where they
cost nothing per adapter. What the wrappers buy over calling
`log_security_event` directly is a signature: a field left out or misspelt
is a type error rather than a record missing a column nobody notices until
the search for it comes up empty. A test holds the two sides together — a
member added to `AuditEvent` with no wrapper reddens the suite.

**`event_type` cannot be overridden, unlike every other field.** On the
three link events the call site wins over the event's own fields, and that
is right for a context field: the caller knows its own context. It is not
right for the event's identity. A login written as `URL_ACCESSED` is not a
record with a wrong field in it — it is a login that a search for logins
never returns, answering "none" rather than "cannot say". So the security
events apply `event_type` last, after the bound fields and after the call's.

**The address is masked, and the whole one stays where it already was.**
`i***@example.com` in the audit journal; `application.log` keeps the full
address, as it already did on registration, sign-in and failed sign-in.
The two journals are read under different permissions, and masking here is
what stops `audit:view` and `logs:view` being two routes to the same
personal data — the audit journal is also the one kept longest, at
`maxsize 1G` and `rotate 200`. What survives the masking is enough for the
questions the journal is read with: whether failures are landing on one
account or many, and whether the domain belongs here at all.

**The account an event is about is `target_user_id`, never `user_id`.**
`user_id` is bound from the request context and means whoever is asking.
On `USER_CREATED` the two are never the same person, and written under one
name the new account would overwrite the administrator — leaving a record
of accounts created and no record of who created them. On the sign-in
events they are usually the same and usually nobody, since the caller is
anonymous until it succeeds; but an already signed-in client may post
credentials for another account, and the collision is the same one.

**The refusals are named in the journal and conflated in the response.** A
wrong password and a deactivated account are one answer over the wire, so
that a guesser learns nothing from the difference. They are two records
here — `invalid_credentials` against `account_deactivated` — because an
operator needs to tell "somebody is guessing passwords" from "a live
credential is being used against an account we switched off", and the
second is the one that may mean the intrusion already happened. The two
readers are different people, and `audit:view` is what separates them.

**Reading a journal is recorded, but polling it is not.** The viewer polls
every five seconds. A record per read would put twelve lines a minute into
the journal being displayed, each of which is then displayed, pushing out
the lines the reader came for — the same reflection the read's own
`log.debug` was already dropped to `debug` to avoid. What is recorded is
the act of going to look: opening the page, switching journals, reaching
into the archives. The refresh marks itself with `follow=true` and is not
recorded; every other control on the page reloads with `follow=false`, and
that flag decides on its own.

It did not at first. This entry said that a request naming the archives was
recorded whatever it claimed about itself, on the reasoning that the page
polls its tail and never the rotated files — which turned out to be untrue
of the page, and the exemption was withdrawn in the entry below ("The
follow flag decides alone, and the terms only describe"). The sentence
stayed here for three days after the code stopped agreeing with it, which
is its own small lesson: a decision revised in a later entry has to be
struck from the earlier one, or the document answers a question two ways
and the reader takes whichever they find first.

**What looking at it changed.** Two things the suite had no opinion about.
Masking applied only to the call's fields left binding as a way around it:
an address bound as `email` reached the record whole on the standard
adapter, whose `_log` merges the bound fields *after* the event's — the
same defect the link events had been fixed for, reintroduced on the new
method. And the first live run of the sign-in events recorded four of the
five outcomes: the fifth request came back `CSRF_TOKEN_INVALID`, because
the run reused one client and a client that has signed in is no longer
anonymous.

### The journals can be searched, and a search says how far it looked

**Decided** (2026-08-18): `GET /api/v1/journals/<journal>` takes six terms
— `event_type`, `account`, `remote_addr`, `short_code`, `since`, `until` —
and the page carries a form for them. The reader applies them while walking
backwards, and stops after 50 000 lines whether or not it has found
anything.

**Why the filter is in the reader.** It is the only part that can stop
early. Filtering above it means the reader hands up everything it looked at
and the caller throws most of it away, which costs the memory the reader
exists to avoid. So `tail` takes the filter, and the page reports
`total_scanned` beside the lines.

**Why a ceiling at all, and why 50 000.** Without a filter the reader stops
as soon as it has the lines asked for, and the size of the journal stops
mattering — that is the property the whole class is built on. A filter
removes it: a search for something absent would walk to the front of the
file. Measured end to end against a 46 MB journal of real-width records, a
filtered read costs 117 to 136 ms whatever it looks for, against 2 ms for
an unfiltered tail; the cost is the scan and not the matching, so a search
finding nothing costs what one filling a page does. At 100 000 the buffer
alone is 36 MB, and four searches at once on `--workers 4` would be most of
a small container. At ten redirects a second the window is about an hour
and a half of a busy service and weeks of a quiet one.

**What the two numbers say together.** `total_scanned` reaching the ceiling
while `reached_start` stays false is the difference between "this account
is not in the journal" and "this account is not in the last fifty thousand
lines". The page says the second one — "Not searched further back than
this" — because the first is a claim the read did not make.

**One account field, not two.** The events carry an account under `user_id`
when it acted and `target_user_id` when it was acted upon, so a role change
names the administrator under one and the account under the other.
Searching one name is a way to see half of what happened to an account and
not notice, and the question an investigation arrives with is "everything
about this account".

**Identifiers exactly, times by prefix.** A substring of an identifier is a
different identifier: `remote_addr` matched by containment answers a search
for `10.0.0.1` with traffic from `110.0.0.199`. The stamps are ISO 8601 in
UTC by one constant and therefore sort as text, so a bound is compared as a
prefix and truncates the stamp to its own length — which is what makes both
ends inclusive, so one date in both fields is that day. A bound that is not
a stamp is refused rather than accepted: compared as text it would sort
past every line and answer "nothing found", which reads as "the journal is
empty" rather than "that is not a time".

The zone designator is part of that refusal, and was not at first. `Z` was
allowed after any prefix, and on anything shorter than the seconds it does
exactly what an unstamped bound does: it sorts after every character a
stamp can carry at that position, so `since=2026-08-18Z` excluded the whole
of 18 August while `since=2026-08-18` included it — two spellings of one
date, one of them silently empty, both accepted by the schema. It is now
tied to the seconds, which is also where ISO 8601 puts it: a date has no
zone to name.

**The follow flag decides alone, and the terms only describe.** Recording a
read was first made conditional on the terms as well: a poll was exempt,
but a poll carrying a search or reaching into the archives was recorded,
on the reasoning that naming terms is somebody asking a new question. It
is not — the page polls whatever is on screen. Nothing in a request tells
new terms from the same terms polled again, and the archives button is
remembered across visits, so the exemption was defeated by the two
controls it exempted: one open tab with a term in the box wrote a line
every ten seconds into the journal it was displaying, and the search that
put them there was pushed out by them. Measured before the fix: 35 seconds
of polling, three lines. The going-to-look is already marked without
guessing — every control on the page reloads with `follow=false`, and only
the timer sends `true`. The terms still go into the record, because "read
the audit journal" and "read the audit journal for one account's failed
logins" are different acts to find afterwards; terms left unset are absent
rather than null.

**What the measurement changed.** Two things, neither visible to the suite.
Walking the file backwards accumulated `buffer = read(step) + buffer`,
which rebuilds everything read so far on every block — quadratic in the
number of blocks, invisible at a page of 200 lines, and 3087 ms against
13.5 ms at 100 000, with the peak RSS following to 2.3 GB. Nothing could
have caught it, because the lines returned are identical and no caller had
a reason to scan past what it returns; a filter has exactly that reason.
And `Refresh now` was bound as `addEventListener('click', load)`, which
hands `load` the event as its first argument — the argument that says "this
is a poll" — so the one press on the page that is unmistakably somebody
going to look was marking itself as a poll and leaving no trace.

The same quadratic shape survived one branch over in the same function.
An archive cannot be read from the end, so it is walked forwards while a
window of the wanted lines is held — and that window was a list trimmed
with `pop(0)`, which moves every entry still in it, once per line of the
file. It stayed cheap only while the window was `HARD_LIMIT`; the filtered
read raised it to `SCAN_LIMIT`, twenty-five times as far to move.
Measured over 200 000 lines at a window of 50 000: 0.89 s against 0.04 s
for a `deque` bounded to the window, byte for byte the same answer. A
wall-clock ceiling holds it, beside the one on the plain branch.

### The security events are counted in the database, and charted beside the journal

**Decided** (2026-08-18): every security event is written to
`security_events` as well as to the audit journal; finished days are folded
into `security_event_days`; `GET /api/v1/journals/counters` serves the
figures, and the journal page draws them.

**Why a second place at all.** The journal answers "what happened" and
cannot answer "how many". It is a file read from its end, and a filtered
read of fifty thousand lines costs 117 to 136 ms and reaches about an hour
and a half of a busy service — so "failed sign-ins over ninety days" is not
a question that file can answer at any price worth paying.

**What the rows hold, and what they deliberately do not.** An event type
and a moment. Widening them to carry the account, the address and the
reason would make the same event exist twice in two shapes that can
disagree, and the one that gets read is the one nobody checks. The journal
stays the record; this is the count.

**Counted by a wrapper, not by a call at each site.** Fifteen events are
written from seven use cases, and a counter invoked beside each
`audit.log_*` is a counter the fifteenth event forgets. `CountingAuditLogger`
implements `AuditLogger`, counts, and delegates — wrapped once in the
container, so no use case knows its events are counted.

**Redirects are not counted here.** They already write to `link_visits`,
through a background task so the redirect itself is not made slower.
Counting them again would put a synchronous insert on the hottest path in
the service to reach a number another table holds, and the guard is on the
event rather than on the method called: `log_security_event` takes any
member of the vocabulary, and one redirect logged that way would
double-count against a figure nobody would think to compare.

**The count is taken before the journal line, in its own transaction.** Its
own, because this logger is handed to use cases that are mid-transaction,
and joining theirs would let a failed count roll back the work it was
recording — an account not created because the service could not count it.
Before, because the journal is what an incident is reconstructed from: a
database failure loses the count and keeps the record.

**A year of retention, against ninety days for visits.** A visit is
traffic: last quarter's redirects answer a question this quarter's answer
better. A sign-in is evidence, and "when did this account last get in, and
from where" is usually asked long after the fact. They also fill at
different rates — ten redirects a second is a million rows a day, while
sign-ins and account changes are counted in thousands. The roll-up is a
command of its own for the same reason: a cron line saying "roll up visits"
should not delete the security history under a name that does not mention
it.

**The figures answer to `audit:view`.** A count is not a weaker version of
a record — it is the same information aggregated, so "eleven failed
sign-ins yesterday" summarises lines a caller without that permission may
not read. `admin:all` still does not carry it, so an administrator is
refused these numbers, and the panel is not rendered for a reader holding
`logs:view` alone: a panel whose every request answers 403 reads as the
service being broken rather than as the reader being unentitled.

**The spans are the visit charts' spans.** Two charts about one service
must be about the same days. They were two copies held equal by a test that
compared them, which saw the names and the widths and not where a span
begins — see *One table of spans, and one place that decides where each
begins*.

**What looking at it changed.** Two faults the suite had no opinion about,
both found by opening the page. The axis along the bottom was empty:
`chartAxis` takes the buckets and reads a moment off each one, and handed a
count instead its loop runs zero times — a chart that looks drawn and says
nothing about when. And the span buttons all looked alike, because the
chosen one was marked with a class of this panel's own invention while
every other button row on the page uses `aria-pressed` — which is also what
a screen reader reads, so the panel was silent about its own state in two
ways at once.

---

### A refusal by privilege is an event, and it is written from one place

**Decided** (2026-08-21): `PermissionDeniedError` is a domain error of its
own, carrying the permissions the caller would have needed and the ones
they tried to hand out; the error handler turns it into
`AuditEvent.PERMISSION_DENIED`.

**Why an event at all.** The journal recorded what administrators did and
nothing about what they tried and were refused — which is the thing an
investigation is usually opened over. Measured on the running stack: a
caller holding `user` asked for the audit journal and for the role list a
second apart, was refused both, and `audit.log` gained nothing either time.
`application.log` gained one line for the first, written by the use case
that refused it and carrying the account, the address and the permission;
for the second it gained `{"error": "Not authorized", "code":
"FORBIDDEN"}` and nothing else — not even a `request_id` to join it to the
`Request completed` line that has one. So refusals were recorded on the
routes that happen to refuse inside a use case, and not on the routes that
refuse in a decorator, which is most of them.

**Why a class and not a code.** Because not every 403 is one of these.
"This would leave the system without an administrator" and "no account may
wear `guest`" are refusals about the state of the service, not about who is
asking; filed as attempted escalation they would bury the ones that are.
The type is what lets one place tell them apart.

**Why from the error handler.** It is where every `PermissionDeniedError`
raised on a route ends up, and one writer cannot forget what seventeen
raisers can — the argument `CountingAuditLogger` is built on. The limit of
it is the CLI, which reaches `DeleteLinkUseCase` with no request and no
error handler; a refusal there is logged by the use case and not recorded.
That is a narrow gap: the CLI runs as whoever has a shell on the host, and
what such a caller can do is not bounded by this application anyway.

**What looking at it changed.** Two things, neither of which the suite had
an opinion about. The first record carried `request_path` and `path` with
the same value in each, because the event named what the bound context
already carried — the arguments went. And `Container.get_audit_logger()`
handed back the component's logger rather than the counted one, so the
first live refusals reached `audit.log` and left `security_events` empty:
the chart on the journal page reported no refusals while the journal
beside it listed two. The accessor had never had an external caller before,
so nothing had noticed that it returns almost — but not quite — the object
the rest of the service uses.

### A page stops asking for what it has just been refused

**Decided** (2026-08-21): the journal viewer and the counters panel stop
their timers on a 401 or a 403, and go on polling through anything else.

**Why.** The viewer polls every five seconds, and a refusal used to change
nothing about that: it painted the message and asked again. Harmless while
a refusal was recorded nowhere, and not harmless the moment one became an
audit event — a permission withdrawn while somebody had the page open
writes twelve lines a minute into the journal, about a reader who has
walked away. A 500 or a dropped connection is the kind of thing that comes
back, so those keep polling; a page that gave up on the first of them would
need reloading by hand.

### A security event is written after its transaction closes

**Decided** (2026-08-21): every use case writes its audit event outside the
`with` block that did the work.

**Why.** `CountingAuditLogger` counts in a transaction of its own — so that
a failed count cannot roll back the work it was recording — and a caller
still holding its own therefore holds two connections at once, on a
deployment of four sync workers, for a row nobody is waiting on. Seven use
cases did it and six did not: two spellings of one act, and the seven were
the expensive one.

The rule is held by a test that reads `COUNTED_ELSEWHERE` out of the
counter rather than restating it, so a link event moved out of that set —
which is what would make its second connection real — reddens rather than
passing quietly.

### The role events say how far they reached

**Decided** (2026-08-21): `ROLE_DELETED` and `ROLE_PERMISSIONS_CHANGED`
carry `holders`, the number of accounts wearing the role.

**Why.** Both acts move every holder at once without touching any of their
accounts, so an investigator asking why an account lost a power finds
nothing against that account — and the record they do find read the same
whether it stripped nobody or the whole staff.

**A count and not a list.** The identities are recoverable from the
`ROLES_CHANGED` records that put the role on each account, while a list
would put an unbounded field into a journal kept at `maxsize 1G`: a role
worn by a thousand accounts would write some forty kilobytes, once, for a
fact already written a thousand times.

### A record names the use case that wrote it

**Decided** (2026-08-21): `BaseUseCase._get_logger` binds the writer's own
`__module__`, and the logger proxy prefers a bound name over the one it was
built with. A name passed on a single call is still ignored.

**Why.** Every application-layer logger is fetched by the DI container,
under the container's `__name__`, and that name was stamped on every line —
the one field a journal record carries about where it came from. Measured
on the running stack: a refused journal read, written from
`ReadJournalUseCase`, arrived as `"logger":
"link_shortener.infrastructure.di.container"`. Seventeen use cases shared
that one name, so filtering the journal by source offered the wiring and
nothing else.

**Bound, not passed.** Where a line came from is a property of its writer,
so a writer may state it once by binding it; a single line may not, or
lines start attributing themselves to whatever the call felt like naming.
The third rendering had to be brought along: `JSONFormatter` wrote
`record.name` while the console formatter beside it and the structlog chain
both preferred the module, so one record read two ways depending on which
file it landed in.

### The rotation configuration is a template, not a finished file

**Decided** (2026-08-21): `dockers/logrotate.conf` names its three journals
by `${LOG_FILENAME}`, `${ERROR_LOG_FILENAME}` and `${AUDIT_LOG_FILENAME}`,
and the rotator container resolves them at start-up from the same
environment the application reads.

**Why.** The names were written into it literally. The application chooses
them from those three settings and the journal viewer reads them from the
same place, so those two agree always; the rotator agreed only while the
defaults were untouched. A deployment writing `LOG_FILENAME=journal` kept
its journals and lost its rotation without a word — `missingok` answers a
missing file with nothing at all, logrotate returns zero, and the file
grows until the disk ends. The suite compared the literal names against the
tree's own defaults, which is not what a deployment runs.

**And the names are now checked.** Nothing looked at them: they are joined
to `LOG_DIR` and given a `.log` suffix by `os.path.join`, which leaves the
directory the moment a name asks it to. A name carrying a separator wrote
outside the log directory, and after this entry the rotator would have
followed it there with `rotate` and `create` in hand. They are validated at
start-up, where a deployment can be told, rather than defended at the join,
where there is nothing sensible to do about it.

### The web layer reads the reader's ceiling from the port

**Decided** (2026-08-21): `HARD_LIMIT` lives on `JournalReaderPort`.

**Why.** `JournalQuery` refuses a `limit` above it, and read it out of
`infrastructure.logging.journal_reader` to do so — the web layer importing
a fact from the layer it is meant not to know. The number is a measurement
of the file reader, but it is also part of the contract: a caller that must
refuse an excess before the read has to know what an excess is, and a
caller told "at most this many" should get the same answer from whichever
reader is wired in.

### A command says what happened; the layer under it only reports

**Decided** (2026-08-24): the modules under `infrastructure/cli/commands/`
return values. The adapter prints them, and it alone decides the exit code.

**Why.** Two of the nine printed for themselves — fourteen `print()` calls
in `cache.py` and `database.py` — and one of them exited as well. That is
not only a matter of taste. `flask cache clear` produced no output of its
own at all: every line an operator saw came from a module that has no
business knowing there is a terminal. And `flask db migrate` was the one
migration command with no error handling in the adapter, because there was
nothing left for it to handle — `migrate_db` had already printed to stderr
and raised `SystemExit`, so the command could not say which database the
failure came from. It returns `(success, output)` now, in the shape
`AlembicCommands` answers in, and the adapter prints and decides.

**What that buys, measured.** The refusal path of `db migrate` had never
been executed by any test; with the decision came the test, and breaking
the exit code reddens it.

### A refusal is one sentence on the error stream, and nothing else

**Decided** (2026-08-24): every command that fails writes a plain sentence
to stderr and exits 1. No prefix, no frame, no report.

**Why.** All three parts were measured as broken, in different commands.

Six refusals of twenty-four carried a prefix, in three spellings —
`ERROR:` four times, `Error:` once, `Error creating link:` once — so a
script grepping for `ERROR` found a quarter of them and read the rest as
success. On stderr the prefix says nothing the stream has not said. A
seventh went through `click.ClickException`, which renders `Error: ` of
its own accord and so survived the sweep that dropped the literals; the
scan that guards this rule now forbids the call as well as the string.

Two commands exited 1 having written nothing to stderr at all —
`maintenance health` and `security check-secrets`, which are precisely the
two most likely to run with their output redirected, being a monitoring
line and a deployment gate. The report stays whole on stdout, because
splitting a table across two streams leaves whoever keeps one of them a
report with holes; what moved is the verdict.

And `link delete` and `link info` printed their rules of `=` around a
refusal that went to the other stream, so a redirected run kept two rules
with nothing between them.

**Measured against the running stack.** With Redis stopped, `maintenance
health` now writes `Unhealthy: Cache, Rate limiter` to stderr and exits 1,
while the four-line report stays on stdout.

### A port declares what its callers need

**Decided** (2026-08-24): `clear_all` and `get_cache_info` are declared by
`CacheMaintenance`, the fifth role `ServiceCache` carries.

**Why.** They were declared by no port at all — present on the Redis and
in-memory implementations, absent from the null one — and two callers
depended on them anyway. The CLI probed with `hasattr` and carried three
branches for what it might find, none of which could run: `delete_stats`
is abstract on `StatsCache`, so the branch reporting it missing was
unreachable, and so were the two below it. The end-to-end test that empties
Redis between journeys said in its own comment that it "reaches past
`ServiceCache`" to call a method the port does not declare. A capability
two callers depend on is one the port owes them.

**The same reading closed a defect next door.** `maintenance check-redis`
reached for `RedisLinkCache._ensure_connection`, a private method of one
implementation, which is documented to answer from what it holds rather
than by asking. Measured against a cache whose backend had gone away:
`_ensure_connection()` returned `True` while `ping()` returned `False`, so
the command an operator runs precisely to find out whether Redis is up
printed "healthy" and exited 0 over a dead one — in the same second
`maintenance health`, which asks the port, printed `Cache: FAILED` and
exited 1. Both questions are now put to the cache, through `CacheHealth`.

### The commands leave the same record the API leaves

**Decided** (2026-08-24): `create-admin`, `create-user`, `security
reset-password` and `db load-custom-roles` write to the audit journal.

**Why.** Each is a second door to an act the HTTP path records, and none of
them recorded anything. The account an operator seeds a deployment with is
typically its only administrator, and it was the one account whose creation
the journal did not hold. The reset is reached for an account believed to
be compromised — the start of exactly the investigation this journal
serves — and it left the account showing a password that changed at a time
nothing accounted for.

`db load-custom-roles` was the widest of them. Measured on the running
stack before the change: one command took `probe:read` off a role and gave
it `admin:manage_users`, and the journal held nothing. It writes
`ROLE_CREATED` for a role it inserts and `ROLE_PERMISSIONS_CHANGED` for one
whose grants it replaces, with what was taken, what was given and how many
accounts wear it. Only where the set actually changed: running the same
file twice rewrites the same associations, and a record of that reports a
change nobody made.

**What is not recorded, and why.** `db load-base-roles` writes nothing.
Seeding is excluded by the rule the vocabulary is built on — the
installation putting its own four roles in place is not somebody being
granted anything, and a journal that records it buries the entries that
matter under every deployment.

**No actor is bound.** A shell has no signed-in user, so the record carries
the `request_id` the command builds — `cli-create-admin`,
`cli-reset-password`, `cli-load-custom-roles` — which is what tells a
reader it came from the console rather than from a request.

### The account listing is ordered by address

**Decided** (2026-08-24): `SQLAlchemyUserRepository.list_all` sorts by
`users.email`.

**Why.** It sorted by nothing, and a listing that takes `limit` and
`offset` needs an order or the paging means nothing. PostgreSQL falls back
to where the row physically sits, so any write moves an account through the
listing. Measured on the running stack: twelve accounts, two windows of
six, then `POST /api/v1/admin/users/<id>/deactivate` on the account at the
top of the first window — it moved past the end of the second, and appeared
on neither. A signed-in administrator does it to themselves, since
`last_login` is a write. The panel walks this listing fifty rows at a time.

**By address rather than by creation time**, which is what the link listing
next door sorts by. `users.email` is unique and already indexed, so the
order is total without a tie-break and costs no index this schema does not
have; `created_at` carries no index, so ordering by it would sort the table
on every page. It is also the column an operator scans a list of accounts
by.

### The two link-and-account listings read their window in one place

**Decided** (2026-08-24): `limit` and `offset` are read by
`web/paging.py`, with a floor of one row, an offset never below zero and a
ceiling of two hundred.

**Why.** The rule was written twice and the copies disagreed. `GET
/api/v1/links/mine` clamped what it read; `GET /api/v1/admin/users` passed
it through. Measured: `?offset=-1` and `?limit=-5` answered 500 on the
account listing and 200 on the link listing — a negative `OFFSET` is not a
query PostgreSQL runs, and there is nothing a caller can do about a 500.
`?limit=100000000` answered 200 with the whole table, a cost the caller
sets and the service pays.

**The ceiling is not a rule about what may be read.** A caller entitled to
the table can still walk it; two hundred is how much of it arrives at once.
The account listing keeps its own default of a hundred, and the link
listing its fifty.

**Not every listing, and deliberately.** The journal endpoints read their
own window through `JournalQuery`, which *refuses* a limit above
`HARD_LIMIT` instead of trimming to it — there a trimmed window would tell
a reader the journal is shorter than it is. The dashboard's account list
reads `page`, not `limit`, and derives the offset from it. What is shared
is the pair of listings that answer "here is some of what you own or
administer", where a window is a convenience rather than a claim.

### A sweep that removed accounts leaves a record

**Decided** (2026-08-24): `CleanUnverifiedAccountsUseCase` writes
`UNVERIFIED_ACCOUNTS_SWEPT`.

**Why.** The accounts go for a reason nobody argues with — an unconfirmed
registration holds its address against its owner — but they go, and an
account ceasing to exist is the widest change to who may do what there is.
`DELETE /api/v1/admin/users/<id>` records exactly that outcome as
`USER_DELETED`. Measured on the running stack before the change: the
security journal held 111 records before a sweep that deleted an account
and 111 after. One fact, on the record through one door and off it through
the other.

**Counts rather than addresses**, for the reason `log_role_deleted` gives
against listing holders: a sweep after a bulk of registrations would put
thousands of addresses into one field of one line, in a journal kept at a
size. The actor is a schedule, so there is no operator to look up either;
what the record answers is that the service removed accounts, how many, and
when.

**Only a sweep that removed something.** A schedule running hourly over a
service with nothing to clean would otherwise write a line an hour saying
so, and the records that matter would sit among them.

**`clean-expired` still writes nothing**, and that stays: a link that
reached its own expiry is not somebody losing an entitlement, and the
account that owns it is untouched.

### A missing account and a taken address answer what the spec already promised

**Decided** (2026-08-25): `UserNotFoundError` and
`EmailAlreadyRegisteredError` are domain errors; a validation error's
status comes from its code.

**Why.** Both situations were already documented the way they are now
answered, and the code disagreed with the documentation rather than with
an opinion. `openapi.py` listed `404 No account carries that id` for
`GET /api/v1/admin/users/{user_id}/stats`, which answered **200** with
four zeroes for an id nothing carries — indistinguishable from a real
account that has never made a link, while the panel's page for that id
answered 404. It listed `409 That address is already registered` for
`POST /api/v1/admin/users`, which answered **400 VALIDATION_ERROR**, the
same code a malformed address carries, while the role route beside it
answered a taken name `409 ROLE_ALREADY_EXISTS`.

**Classes rather than seven hand-built errors.** The "no such account"
sentence was assembled in seven places — the controller twice, the facade,
the service three times, the confirmation use case — for one fact.
`RoleNotFoundError` was made a class for exactly this reason and says so
in its own docstring; the account half had simply never been done.

**`EmailAlreadyRegisteredError` stays a `ValidationError`, and that is
load-bearing.** Public registration does not refuse a taken address out
loud: it answers 202 and mails the address a notice, per OWASP's
Authentication Cheat Sheet. It recognises the clash of a lost race by
catching `ValidationError` with `field == "email"`. A class of its own —
the obvious tidying, since it carries a code of its own — leaves that
catch unmatched and the public endpoint answers 500 where it answers 202,
which is the disclosure the 202 exists to prevent. Measured: with the
class detached, 1178 tests still passed. A test now stands on that path.

**The status now comes from the code** for validation errors too. The
handler returned 400 whatever was raised, so a subclass carrying its own
code could not be answered by it. `VALIDATION_ERROR` is still 400 — that
is what the table says — and a subclass that names a code is answered by
the table, like every other domain error.


## Known limits

Things that are wrong, understood, and deliberately left. Each says what it
would cost to fix.

<details>
<summary><b>The bucketed span stops where the raw rows do</b> — accepted 2026-08-22</summary>

`daily_totals` merges the folded days with the raw visits, so the daily
chart outlives the retention sweep. `summary` — the chart above it, the one
with the span buttons — reads the raw rows alone, so it reaches back
exactly as far as `VISIT_RETENTION_DAYS` and no further.

**Why it is not simply fixed.** `summary` returns three breakdowns beside
its timeline: by device, by browser, and by link. A folded day keeps none
of them — `link_visit_days` holds a total and a robot count. Filling the
timeline from the fold while the breakdowns beside it still came from the
raw rows would put ninety visits above a handful of devices, on one panel,
with nothing saying which figure was the true one. That is a worse defect
than the one it would close: a panel whose figures contradict each other is
worse than a panel that reaches back less far.

**What it costs, and when.** Nothing at the seeded settings: the sweep and
the longest span on offer are both ninety days, and measured on a full
window the two charts agree. Shorten `VISIT_RETENTION_DAYS` below ninety
and they part — measured at seven days, the ninety-day view showed 8 visits
above a daily chart showing 90.

**What it would cost to fix.** Columns on `link_visit_days` for the device
class, the browser family and the link, which turns one row per link per day
into one row per link per day per combination — the table the fold exists to
keep small. The two numbers are held apart by a test rather than left to
drift.

</details>

<details>
<summary><b>The mail-on-request routes answer at two speeds</b> — accepted 2026-08-20</summary>

`POST /api/v1/auth/resend-verification` and
`POST /api/v1/auth/forgot-password` return the same status and the same
sentence for every address. They do not take the same time. The branch with
something to do issues a token and commits a transaction; the branch with
nothing to do returns after one lookup. Measured on the resend route: a
malformed address comes back in 0.12 ms, an unknown one in 0.26 ms, and a
registered one in 0.82 ms, and the three ranges do not overlap. So the body
says nothing about who is registered and the clock says it anyway, to
anybody willing to time a few hundred requests.

What it would cost to fix: doing equal work either way, as
`JwtAuthenticationService` already does at sign-in, where it hashes against
a dummy for an account that does not exist. Here that means issuing and
storing a token for an address with no account behind it, or sleeping to a
fixed budget — the first writes rows for strangers, the second makes every
real request as slow as the slowest one. Neither is worth it while the
throttle stands at three requests an hour per caller — per IP while the
caller is anonymous, which these two routes always are — and that is what
the timing attack would have to be run through. Per caller, not per
address asked about: one IP gets three requests an hour to this route
whatever addresses it names, which is the binding constraint here. It was
written down as "per address" until the auth slice checked it against
`RateLimitMiddleware`, where the key is `client_id:endpoint`.

Stated here because the code used to say it was "written down in the
developer guide", where it was not: a docstring pointing at a note nobody
wrote reads exactly like a documented decision.

</details>

<details>
<summary><b>Self-registration writes no <code>USER_CREATED</code></b> — accepted 2026-08-19</summary>

`USER_CREATED` is written when an operator makes an account, from
`CreateUserUseCase`. An account somebody makes for themselves through
`POST /api/v1/auth/register` is not recorded in the audit journal at all —
the registration is in `application.log` like any other request, and the
first audit record about that account is whatever it does next.

The event is shaped for the operator's case and cannot honestly carry the
other one: `user_id` means whoever is asking and `target_user_id` means the
account it is about, and on self-registration those are the same person,
who did not exist when the request began. Written that way, "who created
this account" is answered with the account itself — which reads as an
administrator having done it, and is the opposite of what the field is for.

What it would cost to fix: either a second event with its own shape, or a
convention that `user_id` may equal `target_user_id` and means "nobody
did". The first is worth doing when the journal is read for account
provenance rather than for privilege changes; the second buys a record by
making an existing field ambiguous. Left as is, and stated here, so that a
reader of the audit journal does not take the absence of a `USER_CREATED`
as evidence that no account was made.

</details>

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
<summary><b>A reader who marks a first read as a refresh leaves no record</b> — accepted 2026-08-18</summary>

`AUDIT_VIEWED` is written for every read except one the caller marks
`follow=true`, which is how the polling viewer avoids writing twelve lines
a minute into the journal it displays. A caller who sets the flag on a
first read is therefore not recorded.

Closing it means per-reader state — remembering who last read what, and
when — which is a store to keep, expire and reason about across four
`sync` workers, for a gap bounded on its own: `audit:view` is granted
separately from `admin:all` and its granting is recorded as
`ROLES_CHANGED`, so a reader can hide a reading but not the entitlement
that allowed it. The alternative considered was suppressing repeats inside
a time window, which needs the same store.

</details>

<details>
<summary><b>A refusal raised off a route is not recorded</b> — accepted 2026-08-21</summary>

`PERMISSION_DENIED` is written by the error handler, which is where a
`PermissionDeniedError` raised on any route ends up. The CLI reaches
`DeleteLinkUseCase` with no request and no error handler, so a refusal
there is written to `application.log` by the use case and not to the audit
journal.

Closing it means either writing the event from each raiser — seventeen call
sites and the eighteenth forgetting, the argument `CountingAuditLogger`
exists to avoid — or giving the CLI an equivalent of the handler, which is
a second place deciding what a refusal is. Left because the gap is narrow
in the way that matters: the CLI runs as whoever has a shell on the host,
and what such a caller can do is not bounded by this application. An
operator who can run `flask link delete` can also read the journals off the
disk and edit them.

</details>

<details>
<summary><b>Refused requests fill the counters as readily as successful ones</b> — accepted 2026-08-21</summary>

Every `PERMISSION_DENIED` is counted in `security_events`, like every other
security event, so a caller probing what they can reach writes a row per
attempt. Nothing rate-limits refusals in particular: what bounds them is
the ordinary throttle, 100 requests a minute per caller by default, and the
daily fold plus `SECURITY_EVENT_RETENTION_DAYS` behind it.

That is the intended shape rather than an oversight — "how many refusals
this week" is the question the counter exists to answer, and a counter that
dropped the refusals would answer it with silence. It is written down
because the arithmetic is worth knowing before it surprises somebody: at
the throttle's ceiling one determined caller can add 144 000 rows a day,
which the fold reduces to one row per event type per day and the sweep
removes a year later.

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
