# Testing

**4526 tests**, 98.59% coverage against a floor of 88%, plus two live runs
pytest does not collect. This page is how to run them and what each level is
actually for.

[All docs](README.md) · [Development](development.md) ·
[Decisions](decisions.md)

## Running them

| Level | Against | Command |
|---|---|---|
| 1 · unit | Mocks instead of a database and cache | `uv run pytest tests/unit/` |
| 2a · integration | In-memory SQLite | `uv run pytest tests/integration/ --ignore=tests/integration/docker/` |
| 2b · integration | Real PostgreSQL and Redis in Docker | `uv run pytest tests/integration/docker/` |
| 3 · e2e | A user's path on SQLite, and the same one on PostgreSQL with Redis | `uv run pytest tests/e2e/` |
| — | Everything | `uv run pytest tests/` |
| — | With coverage | `uv run pytest tests/ --cov=src/link_shortener --cov-report=term-missing` |

The `--ignore` on level 2a is needed: without it 2b is collected too, and
that one wants Docker. Services for 2b start themselves.

```bash
uv run flake8 src tests && uv run pylint src && uv run bandit -r src -q && uv run mypy src
```

## Layout

```
tests/
├── unit/                    # Mocks, in isolation
│   ├── domain/              # Entities, value objects, policies
│   ├── application/         # Use cases, services, ports
│   ├── infrastructure/      # Config, cache, task queue, auth, logging
│   └── web/                 # Controllers, middleware, security, schemas, static
│
├── integration/             # Real in-memory SQLite
│   ├── application/         # Cache against the database, deletion, custom codes
│   ├── infrastructure/      # Repository CRUD, UoW, migrations, log rotation
│   ├── web/                 # API, auth, admin, middleware, templates
│   ├── cli/                 # CLI commands
│   └── docker/              # Real PostgreSQL + Redis
│
├── e2e/                     # Whole user journeys
├── support/                 # Shared machinery: the stack, the rotation writers
├── live/                    # smoke_test.py · browser_test.py · mail_catcher.py
└── load/                    # The locust profile; pytest does not collect it
```

> [!NOTE]
> **The directory decides the category, not a hand-written mark.**
> `pytest_collection_modifyitems` in `tests/conftest.py` applies a marker by
> path: `unit`, `integration`, `docker`, `e2e`. A marker written into a file
> could disagree with where the file lives; this way `-m integration`
> selects exactly what sits in `integration/`.

## The live runs

Neither is collected by pytest — `python_files = "test_*.py"` does not match
their names.

### smoke_test.py — 157 checks over HTTP

```bash
uv run python tests/live/smoke_test.py
```

The exit code is non-zero if any check failed **or if the number of checks
is not 157**: "everything passed" is a statement about the checks that ran,
and says nothing about the ones that stopped running.

Route coverage is not claimed but counted: the run records which rule
answered each request and goes red if one was never touched. Exactly one is
never touched — `/static` — and the file names it.

Counted per **(path, method)**, not per path. Six paths carry two methods
each — `GET` and `DELETE` on a link, `GET` and `POST` on the confirmation
endpoint, four more under `/admin/` — so counting paths alone made those
two answers one entry, and a method added to a path some check already
reached raised no denominator at all. It could ship unchecked with the run
still printing full coverage; measured by registering a `PUT` on a path the
run already drives, the old counter stayed at 48/49 and the current one
names it. `HEAD` and `OPTIONS` are excluded: Flask adds both to every rule
on its own, and demanding a check for each would ask this run to prove
Werkzeug works.

<details>
<summary>Why the run needs ten separate clients</summary>

A Flask test client keeps a cookie jar, so after any request logs in, *every*
later request on that client is cookie-authenticated — and the CSRF layer
refuses unsafe cookie-authenticated requests that carry no token, before the
request reaches any logic. One shared client therefore turned every later
POST and DELETE into a 403 and every "anonymous" check into a check on a
signed-in caller: 32 of 56.

- `guest` never authenticates, so it really is an anonymous caller.
- `api` carries `Authorization: Bearer` and holds no cookies — CSRF does not
  apply to it by construction.
- `session_client` logs in and keeps cookies, which is what a browser is.
- `admin` gets its role written straight into the database, the way an
  operator makes the first administrator.
- `stranger` is a second account: signed in and entitled to nothing here.
  Without it the file has only an owner and an anonymous caller, and every
  per-object authorization check could be deleted from the application with
  this run still green.
- `changer` and `changer_second` are two devices of one further account, and
  they exist because the password-change section replaces that account's
  password. Sharing an account with the sections around it would leave them
  unable to sign in halfway through the run; sharing a client between the
  two devices would make "the other device was signed out" a claim about the
  device that made the change.
- `forgetful` and `forgetful_second` are the same pair for the reset
  section, which replaces a password too — and reads the link out of a
  delivered message, so its account also has to be the only one that was
  mailed anything recently.
- `auditor` is the one whose whole point is what it may *not* do. `admin:all`
  does not carry `audit:view`, so the administrator above cannot stand in for
  it, and the section on the journals needs both sides of that refusal in one
  run.

Each client answers from its own address: registration is limited to three
per hour per address, so a fourth scenario from one address would measure
the throttle instead of what it is named after.

</details>

### browser_test.py — 67 checks in a real browser

```bash
uv sync --group browser
uv run playwright install chromium     # once
uv run python tests/live/browser_test.py
```

This is the only thing that executes `web/static/js`. The rest of the suite
drives the Flask test client, which has no engine in it, so the page scripts
could be broken entirely and stay green.

What it holds:

- **Pages speak sentences, not codes.** Measured: reversing
  `data.message || data.error` in the twelve page scripts that carry it
  turns four checks red on the property itself — the page shows
  `VALIDATION_ERROR`, `VALIDATION_ERROR`, `EMAIL_NOT_VERIFIED` and
  `INVALID_CREDENTIALS` where it should show a sentence — and the run ends
  20/67, because a scenario that cannot read its own refusal never reaches
  its next step. The suite and the HTTP run stay green throughout. (The
  same reversal in `main.js`, which is not a page script, adds nothing to
  either number.)
- **A refusal is shown rather than swallowed.** The page scripts used to
  answer `403` with `if (!resp.ok) return;`, leaving a table on "Loading…"
  for good. One check answers `/links/mine` with a 403 through `page.route`
  and demands a sentence: measured, the silent return puts it back on
  "Loading…" and the check times out, and showing `data.error` instead of
  `data.message` fails it with `FORBIDDEN`.

  It arranged that 403 by assigning `window.fetch` until 2026-08-16, and
  **passed over both defects for as long as it did**. The assignment was
  followed by `page.reload()`, and a reload builds a new document — so the
  script ran against the live service, the table filled in with real rows,
  and "Loading…" went away because the data had arrived. A check that
  fakes a network answer has to do it with `route`, which belongs to the
  page rather than to the document.
- **The confirmation link is inert until clicked**, so a mail scanner that
  follows links cannot spend somebody's token.
- **The language control is alive, and stays alive.** Three checks, and they
  fail for three different reasons: a browser that asks for Russian is
  answered in Russian (measured — Playwright's Chromium sends no
  `Accept-Language` at all unless the context is given a locale, so every
  other check here takes the "declared nothing" branch); pressing a language
  redraws the page and the choice survives a navigation; and the control
  still works **after a Turbo visit**. The last one is the reason the
  handler is delegated to `document`: bound to the buttons instead, it
  passes the middle check and fails that one, which is exactly what was
  measured.
- **What a script *writes* is in the language of the page.** Three more, and
  they fail apart because they reach different strings: a refusal the script
  words itself (the network is cut with `route`, not by replacing `fetch` —
  a replaced `fetch` belongs to the document, and the reload after it builds
  a new one), a table the script draws, and the question a `confirm()` asks,
  which is also the only check that the substitution in `%(code)s` survives
  the trip. Measured: putting any one of the three strings back as an
  English literal reddens its own check and leaves the other two green.
- **A date is written in the language of the page, not the browser's.** The
  same fault arriving through a format rather than through words, and the
  one no scan can find — there is no text in it to look for.
  `toLocaleDateString()` with no argument formats for the browser's locale,
  so a reader who chose Russian on an en-US browser was shown `8/16/2026`
  under a column headed "Создана". The check opens a context with
  `locale="en-US"` and sets the cookie `lang=ru`, so browser and page
  cannot agree by accident. Measured: `'ru'` writes 16.08.2026, `'zh'` writes
  2026/8/16, and dropping the argument again reddens this check alone.
- **The charts are drawn, not merely mounted.** Eight checks, added
  2026-08-16 with `static/js/charts.js`. No run that reads markup can tell a
  chart from an empty panel: the frame, the legend and the controls are in
  the page whether or not a single column was ever painted. These count the
  marks instead — one column per bucket the service sent, against a bucket
  count taken from the answer rather than written into the check — and read
  the axis, hover a column for the breakdown behind it, switch a ring to
  bars and back, and confirm the choice survives a navigation.

  Two of them fake the answer with `route`: an empty span has to put a
  sentence on the plot rather than leave a blank rectangle, and a refused
  one has to say so instead of staying blank.

  The one that pays for itself is **the poll timer does not outlive the page
  that started it**. A page script is re-executed on every Turbo navigation
  and a `setInterval` it started is not stopped by the body being swapped:
  ten navigations leave ten timers polling for statistics nobody is looking
  at. The check sets the interval to 5 s, leaves through the sidebar — a
  Turbo visit, not a load, since a load would discard the timers by itself
  and prove nothing — and counts requests for six seconds. Measured:
  deleting the `turbo:before-cache` listener from `charts.js` lets one poll
  through and reddens this check alone.

  What they do **not** cover: whether the drawing is any good. Nothing here
  would notice a chart that is legible but ugly, or a colour pair that
  fails at a glance. That was decided by measurement elsewhere — the
  palette is validated for lightness, separation and contrast in both
  themes — and by looking at the pages, which is how the interval control
  was found opening in the "off" position on a first visit.
- **One link's own page keeps to that link, and to this account.** Four
  checks. Its address carries a short code, and short codes are guessable
  by construction, so the interesting one asks for a link belonging to
  somebody else and demands two things at once: zero through `scope=mine`,
  and a non-zero total for the same code service-wide, where this account
  is an administrator and may look. Without the second half, "zero" would
  also be the answer for a link nobody has ever opened, and the check
  would pass while proving nothing.

  Measured: changing the page's macro call from `mine` to `service` — the
  one edit that would hand a stranger's traffic to whoever guessed the
  code — reddens that check and only it. A third check watches the code
  reach **both** requests, since the daily chart fetches separately and a
  code threaded into one query and not the other draws one chart about
  this link and one about everything, side by side and unlabelled.

Playwright is declared in its own `browser` dependency group rather than in
`dev`: `uv export` writes the default group and `dev` is that group, so
everything in `dev` lands in `requirements.txt` and the Dockerfile installs
exactly that, while a group of its own is written only when it is asked for.
The export names `--no-group browser` as well, which says the same thing
where a reader of the command can see it. Measured — with playwright
in `dev` the runtime image grew from 540 MB to 731 MB, for a browser the
service never launches.

<details>
<summary>Address confirmation goes through the message, not around it</summary>

Both runs used to skip that seam: the HTTP run minted a token itself and
wrote its digest into `email_verifications`, and the browser run did
`UPDATE users SET email_verified = 1`. Neither exercised the token
registration issues, the link the template builds, or the delivery — and one
of those broke unnoticed.

Both now raise `tests/live/mail_catcher.py`, an SMTP server on the loopback,
point the mailer at it, and take the link out of the delivered message.

Measured by pointing `VERIFY_PATH` at a path nothing answers: the HTTP run
gives 92/157, the browser run 18/67.

The link has to be **opened**, not parsed. The message now leads to a page
whose button posts the token, which tempted the HTTP run into extracting the
token and posting it to a path written inside the run. That is what was done
first — and the broken `VERIFY_PATH` still passed all but one of the checks
the run held at the time, because every account was confirmed anyway.
`confirm_email` follows the address from the message first and spends the
token second.

Two details, each of which cost a green run for no reason.
`EmailMessage.set_content` picks quoted-printable, so in the raw body the
link reads `token=3DAAAA...=\nAAAA`: the catcher has to decode the body or
the token arrives truncated. And the path in the message must not be
compared against a path written in the run itself — the pattern looks for
any address carrying a `token` parameter, otherwise the check restates what
it is meant to check.

</details>

## What the suite is protected from

### A page in the wrong language

Six separate faults produce one symptom, and none of them raises anything:
the page renders, returns 200, and is written in English on a Russian
screen. Each has its own check in
`tests/unit/web/test_translations.py`.

| Fault | Why nothing complains | What catches it |
|---|---|---|
| A string written straight into a template | It is in no catalogue, so there is no empty entry to find | Every readable text node in every template is scanned; anything not marked has to be in a named allow-list of things that are deliberately not prose — API paths, `curl`, the product name |
| An empty `msgstr` | gettext answers the msgid, which **is** the English text | Every entry in every catalogue is checked for a translation |
| An entry marked `fuzzy` | gettext skips fuzzy entries silently; the catalogue looks complete in an editor | No entry may carry the flag |
| A `.po` translated but never compiled | gettext reads `.mo` and never looks at the `.po` beside it | Every translated source entry must be present in the compiled one |
| A string marked but never extracted | It is in no catalogue at all, so the three checks above have nothing to find | Extraction is run again and compared against the `.pot` on disk |
| A sentence written into a page script | It runs in the browser, where the catalogues are not — and nothing but `browser_test.py` executes `web/static/js` at all | Every `.js` under `web/static/js` is scanned the way the templates are, for quoted sentences **and** for text nodes inside the markup a script concatenates; the keys the scripts ask `t()` for are compared with `web/i18n.py:script_strings` in both directions |

The other half — that the wiring between a request and those files holds —
is `tests/integration/web/test_templates/test_pages_come_out_in_the_chosen_language.py`,
which renders pages and reads the words back. The two halves fail apart: a
catalogue can be perfect and unreachable, which is what a wrong
`BABEL_TRANSLATION_DIRECTORIES` produces.

Russian plurals are the reason gettext was chosen over a dictionary of
strings, and they get their own check: three forms, and ten takes the third
— the one a naive `if n == 1` never reaches.

### The machine

`tests/conftest.py` moves each test into an empty directory and strips
**everything** except an explicit allow-list: the run's own variables, the
interpreter's, the locale, the runner's and the Docker daemon's.

That is not the first attempt. The previous three went the other way round,
listing what to remove, and each missed something:

| What was listed | What it missed |
|---|---|
| variable names | `DATABASE_TYPE`, `DATABASE_NAME`, `DATABASE_HOST`, `DATABASE_USER`, `DATABASE_PASSWORD` — only `DATABASE_URL` was named |
| configuration classes | `CeleryConfig` with `CELERY_BROKER_TIMEOUT`, which lives outside the application profiles |
| `EnvField` descriptors | `DATABASE_POOL_SIZE`, `DATABASE_MAX_OVERFLOW`, `DATABASE_POOL_RECYCLE` — declared as properties reading `read_env` |

The miss had the same shape every time: the configuration grew a new way to
name a setting that the enumeration did not know about. An allow-list ends
that — a new setting is covered the moment it appears, whatever idiom
declares it.

The protection is itself tested:
`tests/unit/infrastructure/test_config/test_env_isolation.py` plants settings
from a **module-scoped** fixture — that is, before `detached_env` runs — and
checks that none reaches the test.

### Silent skips

> [!IMPORTANT]
> An unreachable Docker daemon is a legitimate skip: the machine cannot run
> those tests. Everything else is a failure. The distinction was not there
> from the start — once the test stack failed to come up on a taken port,
> every branch reported `skipped`, and the run came back green:
> `492 passed, 16 skipped` where it used to be `508 passed`. Only counting
> noticed.

### Migrations

`integration/infrastructure/database/test_migrations.py` runs the revision
chain against a real database file. Every other test builds the schema with
`create_all` from the models and executes no revisions — which is how a
broken migration stayed unnoticed for a long time.

**And against PostgreSQL, which is a different question.** That file uses
SQLite, because that is what a clone gets out of the box; deployments run
on PostgreSQL, and the two disagree about what a migration may say.
`integration/docker/test_migrations_on_postgresql.py` builds a database of
its own on the real server and runs `alembic upgrade head` into it.

It exists because of what SQLite accepted: `link_visits.is_bot` was
declared `server_default=sa.text('0')`, an integer default on a boolean
column. SQLite took it and the whole suite was green. PostgreSQL refuses
it — *column "is_bot" is of type boolean but default expression is of type
integer* — and since a revision runs in one transaction, the refusal left
a deployment with **no schema at all**: the migration container exited 1
and the application came up against nothing. Measured by bringing the
stack up on empty volumes, which is the one thing no test did.

### A rotation nobody follows

The journals are rotated from outside the application, and every way that
arrangement breaks is silent — the service keeps answering, and the writing
goes somewhere nobody reads. Four checks, in three places, because no one of
them can ask the whole question.

| Fault | Why nothing complains | What catches it |
|---|---|---|
| The handler is swapped for one that does not notice a rotation | Records go on being written — into the file that was moved aside, which the retention policy eventually deletes | `test_rotation_is_followed.py` moves the file and reads both sides; it also asserts that all three journals `setup_logging` installs are watched ones |
| The handler rotates for itself | With one process it works; with the four gunicorn runs it truncates a file the other three are writing | `test_rotation_under_several_writers.py` runs four writer processes against one journal while a fifth renames it, and counts every record back |
| The shipped configuration names a file nobody writes | `missingok` is in it on purpose, so a path that matches nothing rotates nothing and says nothing | `dockers/logrotate.conf` is a template: it names the three journals by the settings that choose them, and the test holds those variable names against the profile's own — plus a Docker run that renames all three and checks logrotate follows |
| The configuration does not parse | logrotate skips the block it cannot read and carries on | `test_logrotate_config_is_accepted.py` builds the rotator image and runs `logrotate -d` over the shipped file. Written the obvious way, that file said `create 0640 1000 1000` and the Debian build answered `unknown user '1000'` — it looked right and rotated nothing |

The last one needs Docker and skips without it, the way the rest of the
container-backed checks do.

### Documentation that has drifted

A document is code nobody compiles: it stays grammatical after it stops
being true, and the reader has no way to tell. Eleven tests read these
documents and hold them against the tree.

**Against what the service does**

- `test_documented_rate_limits.py` parses the limits table in
  [Configuration](configuration.md#rate-limits) and holds it against
  `BaseConfig.RATE_LIMITS`. A published limit the service does not enforce
  is a failure — a limit is a security decision, and a document naming the
  wrong one is worse than one naming none, because it is believed.
- `test_api_docs.py` holds `/api/openapi.json` against the real URL map: a
  new endpoint is a failing test rather than an undocumented endpoint.
- `test_the_documented_json_matches_the_answer.py` holds the JSON examples
  in [Getting started](getting-started.md) and [Operations](operations.md)
  against the bodies they illustrate — field names, not values. Two of them
  had drifted: the shorten example was four fields short in both languages,
  and the health example six.
- `test_the_documented_api_counts.py` holds the sentence in
  [Development](development.md) that states how many paths and operations
  the API document describes.
- `test_the_documented_matrix_is_coherent.py` parses the table of ways to
  arrange the stack and refuses a row that contradicts itself.
- `test_every_setting_has_its_line.py` holds `.env.example` to being the
  exhaustive list every other document says it is.

**Against the numbers they publish**

- `test_documented_live_run_sizes.py` reads the size of each live run out
  of the script by `ast` and holds six documents to it.
- `test_the_documented_suite_size.py` holds the nine places that publish
  the size of the suite to one number, and the gap the workflow's comment
  names to the gap it has.
- `test_the_documented_decision_count.py` counts the write-ups in
  [Decisions](decisions.md) two ways and holds the three documents that
  state the number — in words, in two languages — to it.

**Against each other**

- `test_the_translations_carry_the_same_facts.py` compares the two READMEs,
  and the two tutorials, on everything that is not prose: settings,
  commands, routes, permissions, images, numbers. It is what found a
  screenshot the Russian tutorial never had.
- `test_the_documentation_links_resolve.py` follows every internal link and
  every anchor in every markdown file. An anchor is the half that rots
  quietly: renaming a heading is an ordinary edit, and it breaks every link
  pointing at it without touching them.

One more sits beside them and works the other way round. It reads no
document: it holds the *behaviour* two of them publish a table about.
`test_the_own_domain_needs_no_cors_entry.py` walks all four rows of that
table — whether the form after a sign-in is admitted, for an origin that is
the service's own address and for one that is not, with `CORS_ORIGINS`
empty and with it named. The table was written after a claim in a
deployment guide turned out to be wrong in a way nothing could have caught:
the guide said the own address had to be listed, and the CSRF layer had
been adding `BASE_URL` on its own all along.

## Mail in development

The development overlay raises Mailpit, a catcher that accepts SMTP on 1025
and delivers nothing anywhere. Everything caught is visible at
`http://127.0.0.1:8025`.

```bash
docker compose --env-file .env.docker up -d mailpit
curl -s http://127.0.0.1:8025/api/v1/messages | python3 -m json.tool
```

A catcher rather than "write mail to a file in dev": the same code runs
through it as in production — `smtplib`, the SMTP conversation, header
assembly. A "development does it differently" branch does not exercise that
path and breaks quietly.

The suite sends no mail under any machine configuration: `TestingConfig`
declares `MAIL_ENABLED = False` as a plain attribute, which overrides the
environment descriptor entirely.

## What CI enforces

The suite runs **twice**, in a clean environment and in a hostile one, to
catch tests that read configuration nobody gave them.

```mermaid
flowchart TD
    subgraph clean["clean"]
        C1[uv sync --locked] --> C2[requirements.txt vs uv.lock]
        C2 --> C3[count collected tests<br/>minimum 4200] --> C4[pytest --error-for-skips]
        C4 --> C5[smoke_test.py<br/>157 checks] --> C6[browser_test.py<br/>67 checks]
    end
    subgraph hostile["hostile"]
        H1[the same, plus a polluted .env<br/>and exported variables] --> H2[pytest --error-for-skips]
        H2 --> H3[smoke_test.py]
    end
```

Beyond "the tests passed", five things are checked:

| | Why |
|---|---|
| The number of collected tests, as a floor | "N passed" means nothing until you know how many were collected. A file that stops being collected gives a green run with a smaller N |
| The exit code of collection, before the count | An interrupted collection prints a plausible number and exits 2 |
| `--error-for-skips` | A skip is a failure, except for the Docker daemon |
| `requirements.txt` against `uv.lock` | Otherwise the image ships a different set of packages than CI tested |
| The live runs | They are the only thing that walks every routing rule and executes the page scripts |

The browser run is on the clean half only: it reads nothing from the
environment, and Chromium is a hundred megabytes to download.

Linters are a separate job, one pass, with a step each so the summary says
which tool objected: `flake8`, `pylint` (floor 9.0, and the run prints what
it scored), `bandit`, `mypy` (floor: zero errors). A fifth step in that job
checks nothing about the code: it re-runs `pybabel extract` and compares the
result with `messages.pot`, ignoring the creation date. A `#:` line in that
template is the address a translator opens, and it goes out of date on any
edit that shifts a line — silently, because `gettext` reads the compiled
`.mo`, where those addresses are not present at all.
