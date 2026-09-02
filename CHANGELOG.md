# Changelog

Notable changes to this project, newest first.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Every number below was measured on the tree it is written against, not
recalled — the same rule the rest of this project's documents are held to.

## [Unreleased]

## [0.9.0] — 2026-09-02

First public release.

**Why 0.9.0 and not 1.0.0.** The service is complete and measured, but its
HTTP contract has never met a caller outside this repository. Semantic
versioning's promise is that a major version will not break you; that
promise is worth making once there is somebody to make it to, and worth
keeping once made. Until then a version that says "finished, not yet
frozen" is the honest one.

Nothing before this was published, so `Fixed` and `Changed` below record
corrections made during development rather than changes a reader has to act
on. They are kept because each says what the service now does and why it
does it that way.

### Added

- **Guest links** — shortened without an account, seven-day life, quota per
  address. The deletion token in the answer is how a link with no owner is
  removed, ownership having nothing to match against.
- **Accounts** — permanent links, personal statistics, a dashboard, and
  email confirmation that never reveals whether an address is already taken.
- **Batch creation** — several URLs per request, with per-item results, so
  one bad URL does not fail the rest.
- **Deduplication within an owner** — shortening your own URL again returns
  your own live link rather than a second one.
- **Role-based access control** — five roles (`guest`, `user`, `analyst`,
  `auditor`, `admin`) over fifteen permissions, seeded from YAML and
  editable through the panel. A signed-out visitor acts as `guest`, a real
  role, rather than as a branch in the code. `admin:all` deliberately does
  not carry `audit:view`: an administrator is the person an audit trail is
  kept against.
- **HTTP API** — 39 operations across 33 paths, published at
  `/api/openapi.json` and generated from the same Pydantic models the
  endpoints validate against, so the document cannot describe a service
  that is not there.
- **Command-line interface** — 36 commands in seven groups, plus
  `create-admin` and `create-user` outside them: migrations, seeding,
  maintenance sweeps, cache, statistics, secrets, users, roles and tokens.
- **Two-level cache** — redirects and link objects in Redis, invalidated on
  delete, degrading to a null implementation rather than taking the request
  down.
- **Asynchronous click counting** — clicks and outgoing mail handled by
  Celery, off the request path.
- **Rate limiting** — on every route, tighter on authentication and link
  creation, with `/health` and `/static/` exempt.
- **Audit journal** — security events written outside the transaction they
  describe, readable through the panel and the API by `auditor`.
- **Interface in English, Russian and Chinese**, chosen by `Accept-Language`
  and a cookie, with the service's own sentences translated as well as the
  pages.
- **Docker Compose stack** — application, PostgreSQL, two Redis instances,
  a Celery worker and log rotation, with a development overlay.
- **Test suite** — 5210 tests, 98.65% statement coverage against a floor of
  88%, plus two live runs against a real stack: 159 HTTP checks and 71
  browser checks. CI runs the suite twice, in a clean environment and a
  polluted one.

- **A QR code for every link.** `GET /api/v1/links/{code}/qr` answers an SVG
  document, and the dashboard shows it on a link's own page and links to it
  from the table. The square encodes the **short** address and never the
  destination: a code carrying the destination scans perfectly and defeats
  the link — no click recorded, no expiry honoured, and deleting the link
  leaves every printed copy pointing at the target for good. The code is
  resolved before anything is drawn, so an address that leads nowhere is a
  `404` rather than a square that leads to one. SVG rather than PNG, with
  both a `viewBox` and a default `width`, so one document prints on a
  poster and renders in a table cell. Adds one dependency, `segno`: pure
  Python, no dependencies of its own, and it writes SVG directly.

- **`ALLOWED_HOSTS`.** The service answered to any `Host` it was given,
  including a name somebody else pointed at its address. Empty by default,
  which is what it has always done — nothing here reads `request.host`, and
  `short_url` is built from `BASE_URL`, so the door led nowhere. Named, and
  any other `Host` is refused with `400` before authentication runs. A
  deployed profile that leaves it empty now says so at startup, the way an
  empty `TRUSTED_PROXIES` does.

- **Four more faults a deployed profile refuses to start on.** `CORS_ORIGINS=*`
  beside `supports_credentials=True`, which makes flask-cors echo the
  caller's own `Origin` and add `Allow-Credentials: true` — measured on the
  installed version, so any page anywhere reads this service's answers as
  whoever is signed in. A journal name that is a path, which the three
  journal settings are joined to unexamined: `LOG_FILENAME=../../etc/…` is
  a file the application creates and appends to for as long as it runs. A
  `SESSION_COOKIE_SAMESITE` Werkzeug will refuse later, which started
  cleanly and then raised out of every response that touched the session.
  And a language tag the catalogue machinery cannot carry, so `pt-BR` is
  refused where `pt_BR` is meant. Only the deployed profiles: `development`
  is a machine where a wide setting costs nothing, and a profile nobody
  named resolves to it.

- **A guest lifetime longer than the ceiling is refused too.**
  `_validate_ttl` compares what a caller *asked* for against
  `MAX_TTL_SECONDS`, and the guest ceiling is applied after it — so a guest
  asking for nothing walked straight past the limit. Measured at 10 and
  1000: a guest link came out at 1000 seconds while a guest asking for 50
  was refused for exceeding 10, which left the ceiling binding everyone
  except the callers it was written for.

### Fixed

- **A request body had no upper bound.** Flask leaves `MAX_CONTENT_LENGTH`
  unset, nothing stands in front of gunicorn, and `request.get_json()`
  reads the whole body into memory *before* any validation — so the size of
  an anonymous request was decided by the client. Measured on the
  production profile: one `POST /api/v1/shorten` carrying 60 MB was
  accepted whole and only then answered `400`; four concurrent 200 MB
  bodies took the container from 342 MiB to **1.598 GiB** and 356 % CPU,
  from four `curl` commands and no account. The per-endpoint throttle does
  not help — it counts requests, and four are enough to hold four
  synchronous workers. Now one mebibyte by default, and `validate()`
  refuses a value too small to hold the largest batch the service admits.

- **An address longer than its column answered `500`.** `users.email` is
  `String(255)` and nothing above it said so, so a 261-character address
  travelled the whole way down and was refused by PostgreSQL — which does
  not raise `ValidationError`, so no handler knew it, and an
  **unauthenticated** two-field body to `POST /api/v1/auth/register`
  answered `500`. The bound is now `Email`'s, at the standard's 254
  characters, and the answer is `400` with the field named. SQLite is why
  the suite never saw it: it ignores a declared width, stores the row and
  reports nothing.

- **Nothing counted failed sign-ins per account.** `RATE_LIMITS["auth.login"]`
  counts by address, which bounds one guesser: a hundred addresses trying
  one account met a hundred separate budgets and no counter carrying the
  account's name. `LOGIN_ACCOUNT_FAILURE_LIMIT` is that counter — ten wrong
  guesses per fifteen minutes by default, refused with the same
  `INVALID_CREDENTIALS` as any other failure so that it names no address.
  Only a wrong password spends it: a right password against a deactivated
  or unconfirmed account is not a guess, and counting it would let anyone
  holding a valid credential lock its owner out. Refused rather than
  delayed, because a sleeping request holds a synchronous worker and four
  of those are the whole service.

- **`admin:manage_users` reached accounts it could not have created.**
  `require_may_confer` guarded handing a permission out; nothing guarded
  taking one away, and deleting, deactivating and re-roling all take. So a
  role carrying `admin:manage_users` and nothing else could remove the only
  `auditor`, and with it the only account able to read the audit journal —
  which is exactly the separation `admin:all` not carrying `audit:view`
  exists to make. Guarded now by `require_may_act_on`, which compares only
  *privileged* permissions: an account that merely signed up holds
  `link:view_own`, which an administrative role has no reason to carry, and
  a plain set difference would have refused the work the role exists for.

- **A demoted logging chain wrote the message and dropped every field.**
  `ProcessorFormatter` was built without a `foreign_pre_chain`, so a record
  arriving through stdlib logging carried nothing bound to it. Reproduced:
  `StandardLogger(...).bind(request_id=…, user_id=…).info("Link created",
  short_code=…)` wrote `{event, level, logger, timestamp}` and nothing
  else — the four fields an investigator opens the journal for, gone, at
  `200`, with the line present and looking right. That is the state the
  failover machinery demotes into, so the journal was at its least
  informative exactly when something had already gone wrong.

- **Both journal formatters wrote the sentence and dropped the stack.**
  `record.exc_info` was never read, so `logger.exception(...)` and
  `exc_info=True` reached the file as one line with no cause under it —
  every unhandled error in the service. `StandardLogger` also turned
  `exc_info=None` into `True`, which the port documents as "no traceback"
  and the structlog adapter beside it honours, so the two wrote different
  journals from the same call.

- **Three administrative routes acted on an account without asking whether
  the caller may reach it.** `activate`, `verify-email` and
  `resend-verification`, while delete, deactivate and re-role all passed
  through `require_may_act_on_user`. Each hands out or takes back the
  ability to sign in, so on an account holding a privileged permission the
  caller does not, they handed out exactly the authority that rule exists
  to keep out of their hands. The third needed a use case of its own: the
  public endpoint runs the same one, where the caller is anonymous and
  there is nobody to check.

- **A negative `ttl_seconds` meant "forever".** The guest ceiling is
  applied with `min()`, so a negative value walked past it and made a link
  that never expires for a caller allowed seven days.

- **`flask db migrate` reported success while doing nothing.** With
  `USE_ALEMBIC=false` it printed to stdout and exited `0`, while the
  `alembic` group refuses the same request and exits `1` — so a deployment
  line reading `flask db migrate || exit 1` was told the schema was up to
  date on a deployment where nothing had run. The refusal is one sentence
  now, said in both places. The start-up hint for an absent schema followed
  suit: it named `flask alembic upgrade head` whatever the flag said, so a
  deployment running with it off was told, on every start until it had a
  schema, to run the one command that configuration refuses.

- **The role-name field applied no client-side check at all.** HTML compiles
  the `pattern` attribute with the `v` flag, where `[A-Za-z0-9_-]+` is not a
  valid character class: the browser logged `Invalid regular expression …
  Invalid character in character class` on every load of the form and then
  admitted everything. Measured — `bad!` passed `checkValidity()`. The
  string is valid to `re` and to Pydantic, so only a browser could see it.

- **`flask maintenance health` called a working cache a failure.** It read
  its verdict out of the strings it had just rendered, so a cache keeping
  entries in this process — reported as `in_process`, which is not a
  failure — was counted as one and took the command's exit code with it.

- **The models and the migration disagreed about five defaults.** Columns
  across `link_visits`, `link_visit_days` and `security_event_days` carry a
  `server_default` in the migration and none in the model, so a row written
  by anything that does not go through the ORM got one default and a table
  built from the models in a `USE_ALEMBIC=false` deployment got another,
  which is `NULL`.

- **A hash with a trailing newline was accepted as that hash.** `UrlHash`
  matched with `re.match`, and `$` in Python matches before a trailing
  newline — the deduplication entry is keyed by exactly that value. A host
  with a trailing dot was refused in the other direction, though
  `a.example.` and `a.example` are one name to DNS; 21 probes confirm every
  SSRF vector with a dot on the end is still refused.

- **`User-Agent` parsing called Edge and Opera on iOS Safari**, and an
  ordinary Android tablet a phone: `edgios`, `opios` and `opt` were in no
  pattern, and `android` matched the tablet rule before `mobile` could say
  otherwise. `is_recent` and `is_expired` raised `TypeError` on a timestamp
  without a zone, which is what four adapters hand back.

- **A journal search stopped at the health probe.** The probe filter hid its
  own event type instead of skipping it, so a search for anything else
  answered `False` at that line and `LOGGING_CHAIN_PROBE` swallowed every
  other term in the query.

- **The published document promised answers the routes cannot give.** Six
  operations carried a hand-written `415` beside the one the builder folds
  in, so the same refusal was stated twice; `auth/refresh` and `auth/logout`
  were promised a `415` for a request they accept. The security example
  published buckets that did not add up to the totals beside them, and the
  extended link example published a `deletion_token` that endpoint does not
  return.

### Changed

- The `auditor` role now holds `stats:view_basic` and `stats:view_full`.
  Without them it saw less than nobody: measured on two live walks,
  `GET /api/v1/stats` and both visit endpoints answered 200 to an
  anonymous caller and 403 to a signed-in auditor, so whoever read the
  journals about an incident could not see the traffic while it happened.
  It remains a reading role.

  **A database that already holds the roles keeps the old set.** Seeding
  leaves an existing role alone on purpose, so an edit made in the panel
  survives — which means `flask db load-base-roles` will not add these.
  Take them from the shipped file with
  `flask db load-custom-roles src/link_shortener/infrastructure/configs/rbac/roles.yaml --update-existing`,
  or add them to the role in the panel.

- Request bodies refuse a field the service does not declare, with `400`
  and the field named, where they used to ignore it. `POST /api/v1/shorten`
  answered `201` to `{"url": ..., "custom_code": "..."}` and gave a
  generated code: there is no custom code in the HTTP API, and the caller
  had no way to learn they had not been given one. `RefreshTokenRequest`
  stays lenient, because both routes that use it are reached with no body
  at all and a stray field must not refuse a logout.

- Deleting a role puts the accounts it leaves with no role at all back on
  the default one. Such an account could sign in and was then refused
  everything, including what an anonymous caller may do.

### Notes

- The project is licensed under Apache 2.0, and contributions come in under
  the same terms by section 5 of that licence, certified by a DCO sign-off
  rather than a CLA.
- The name on the pages is MaizLink; the Python package is
  `link-shortener`.

[Unreleased]: https://github.com/IAMN1/link-shortener/compare/v0.9.0...HEAD
[0.9.0]: https://github.com/IAMN1/link-shortener/releases/tag/v0.9.0
