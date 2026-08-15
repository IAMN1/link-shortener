# Contributing

Thanks for looking. Bug reports, questions and patches are all welcome.

## Before you write code

Open an issue first for anything larger than a fix. It costs you nothing and
saves the case where a change is written well and then turned down for a
reason nobody could have guessed from the outside.

For a bug, the most useful report says: what you did, what happened, what
you expected, and which profile you were on (`development`, `staging`,
`production`, Docker or local).

## Setting up

```bash
uv sync
cp .env.example .env
uv run flask security generate-secrets   # paste both into .env
uv run flask alembic upgrade head
uv run flask db load-base-roles
uv run pytest tests/
```

[Getting started](docs/getting-started.md) has the same thing with the
expected output of every step.

## What a change has to pass

```bash
uv run pytest tests/                      # 2664 tests, 88% coverage floor
uv run flake8 src tests
uv run pylint src                         # floor 9.0
uv run bandit -r src -q
uv run mypy src                           # floor: zero errors
```

Plus the two live runs, if your change touches HTTP or the frontend:

```bash
uv run python tests/live/smoke_test.py    # 123 checks
uv run python tests/live/browser_test.py  # 18 checks, needs --group browser
```

CI runs all of it, twice — once in a clean environment and once in a
polluted one. [Testing](docs/testing.md) explains what each level is for.

## House style

The code is written to be read by someone who was not there when it was
written. Concretely:

| | |
|---|---|
| **Comments say why, not what** | The code already says what. A comment earns its place by explaining a decision, a measurement, or a trap |
| **Numbers are measured** | If a docstring or a document states a number, it came from a run. Say which |
| **A test names the defect it prevents** | `test_the_last_administrator_cannot_be_deleted`, not `test_delete_user_4` |
| **New behaviour comes with a test that fails without it** | Write the test, watch it go red, then fix it. A test that never failed proves nothing |
| **Documentation is part of the change** | A new setting means a line in `.env.example`; a new endpoint means an entry in `web/schemas/openapi.py` — there are tests that fail if you skip either |

If a decision would make a reader stop and wonder, add an entry to
[Decisions](docs/decisions.md) in the same three-part shape the others use:
what was decided, why, and what was left open.

## Sign your commits off (DCO)

Every commit needs a `Signed-off-by` line:

```bash
git commit -s -m "fix: the roles column was blank for every account"
```

That adds:

```
Signed-off-by: Your Name <your.email@example.com>
```

The line means you agree to the [Developer Certificate of
Origin](https://developercertificate.org/) — in short: you wrote this, or
you have the right to submit it, and you are fine with it being distributed
under the project's licence.

> [!NOTE]
> This is why the sign-off is asked for rather than a full CLA: it is one
> flag on `git commit`, and it keeps the project's licensing coherent. The
> project is under [Apache 2.0](LICENSE), and contributions come in under
> the same terms.

## Commit messages

One or two lines, in the imperative, saying what changed and — if it is not
obvious — why. Look at `git log` before writing your first one; the style
there is the style.

```
fix(dashboard): show the roles each account holds

The column read `role.name` over a list of names, which Jinja prints as
nothing, so it was blank for every account in the service.
```

## What is unlikely to be merged

- A change with no test, where a test was possible.
- A refactor with no defect behind it. The code has a shape on purpose; a
  change that only moves it costs review time and buys nothing.
- A new dependency for something the standard library does.
- Documentation stating a number nobody measured.
