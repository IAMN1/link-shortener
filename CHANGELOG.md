# Changelog

Notable changes to this project, newest first.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Every number below was measured on the tree it is written against, not
recalled — the same rule the rest of this project's documents are held to.

## [Unreleased]

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

## [0.9.0] — 2026-08-30

First public release.

**Why 0.9.0 and not 1.0.0.** The service is complete and measured, but its
HTTP contract has never met a caller outside this repository. Semantic
versioning's promise is that a major version will not break you; that
promise is worth making once there is somebody to make it to, and worth
keeping once made. Until then a version that says "finished, not yet
frozen" is the honest one.

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
- **Test suite** — 4941 tests, 98.66% statement coverage against a floor of
  88%, plus two live runs against a real stack: 157 HTTP checks and 68
  browser checks. CI runs the suite twice, in a clean environment and a
  polluted one.

### Notes

- The project is licensed under Apache 2.0, and contributions come in under
  the same terms by section 5 of that licence, certified by a DCO sign-off
  rather than a CLA.
- The name on the pages is MaizLink; the Python package is
  `link-shortener`.

[Unreleased]: https://github.com/IAMN1/link-shortener/compare/v0.9.0...HEAD
[0.9.0]: https://github.com/IAMN1/link-shortener/releases/tag/v0.9.0
