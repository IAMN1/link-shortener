# Decisions

Thirty-nine write-ups of why something is the way it is. Read this when the
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

### One link's traffic belongs to whoever owns the link

**Decided** (2026-08-19): `?code=` on `/api/v1/stats/visits` and
`/api/v1/stats/visits/daily` is checked against `can_view_link_details`,
the same gate the extended link endpoint uses.

**Why.** Both endpoints hold `stats:view_basic`, which the `guest` role
carries — that is deliberate, because the service-wide answer is a count
nobody owns. A named code is not that answer. Measured against the running
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
a translator with no way to see where they appear.

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
that adds the events worth counting.

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
