# Changelog

Notable changes to this project, newest first.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Every number below was measured on the tree it is written against, not
recalled — the same rule the rest of this project's documents are held to.

## [Unreleased]

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
- **Command-line interface** — 38 commands in seven groups, plus
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
- **Test suite** — 4219 tests, 98.60% statement coverage against a floor of
  88%, plus two live runs against a real stack: 157 HTTP checks and 67
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
