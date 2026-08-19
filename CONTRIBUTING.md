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
uv run pytest tests/                      # 3171 tests, 88% coverage floor
uv run flake8 src tests
uv run pylint src                         # floor 9.0
uv run bandit -r src -q
uv run mypy src                           # floor: zero errors
```

Plus the two live runs, if your change touches HTTP or the frontend:

```bash
uv run python tests/live/smoke_test.py    # 141 checks
uv run python tests/live/browser_test.py  # 55 checks, needs --group browser
```

CI runs all of it, twice — once in a clean environment and once in a
polluted one. [Testing](docs/testing.md) explains what each level is for.

## If you touched a string a visitor reads

The interface is offered in English, Russian and Chinese. Text on a page
goes through `gettext`, and so do the sentences the service itself writes —
the `message` in an error envelope, and the messages it mails. A new or
edited string means the catalogues have to be brought along with it:

```bash
D=src/link_shortener/web/translations
uv run pybabel extract -F babel.cfg -o $D/messages.pot \
    --project=link-shortener --version=0.1.0 .
uv run pybabel update -i $D/messages.pot -d $D          # merge, keeping what exists
# …fill in the new msgstr in $D/ru/LC_MESSAGES/messages.po and zh/…
uv run pybabel compile -d $D                            # .mo is what gettext reads
```

`update`, never `init` — `init` starts an empty catalogue and throws away
every translation already made. `init` is only for a language that has none.

Six things go wrong here and **none of them raises anything**: the page
just comes out in the wrong language. A string written straight into a
template, an empty `msgstr`, an entry marked `fuzzy` (gettext skips those
silently), a `.po` translated but never compiled, a marked string that
extraction never reached, and a sentence typed into a page script all look
identical from outside. `tests/unit/web/test_translations.py` catches all
six, and it is the reason each of them is a test rather than a note here.

Marking is `{{ _('…') }}` for a plain string, `{% trans %}` for a sentence
with a link or a number in it, and `pgettext('context', '…')` where one
English word needs two translations — "Sign up" is a button in the header
and a verb inside a sentence, and Russian will not use one word for both.

**A sentence the service raises is marked, not translated, where it is
written.** The domain does not import Flask-Babel — the CLI and the Celery
worker raise the same errors with no request to negotiate with — so it
marks with `N_` from `domain/i18n.py` and `web/i18n.py:translate_error`
does the lookup at the boundary. A sentence with a value in it carries a
`template` and `params` beside the finished English one:

```python
raise ValidationError(
    f"ttl_seconds must not exceed {self.max_ttl_seconds}",   # logs read this
    field="ttl_seconds",
    template=N_("ttl_seconds must not exceed %(max)s"),      # the catalogue reads this
    params={"max": self.max_ttl_seconds},
)
```

An f-string alone is one more silent way to lose a translation, alongside
the six above: it is finished before anyone can look it up, `gettext`
hands it straight back, and the answer comes out English with nothing
reporting a fault. Placeholders are named, never `%s` — a translator moves
them.

Sentences behind a 5xx are deliberately **not** marked. The handler answers
one generic sentence for all of them, so marking would only put the
service's internals in front of a translator.

**A sentence a page script writes is not written in the script.** It runs in
the browser, where the catalogues are not, so a string typed into a `.js`
file stays in that language on every page. Add it to
`web/i18n.py:script_strings`, which `layout/base.html` prints into the page,
and ask for it by key:

```javascript
tbody.innerHTML = '<tr><td colspan="4">' + escapeHtml(t('no_links_yet')) + '</td></tr>';
if (!confirm(t('confirm_delete_link', { code: code }))) return;
```

The key has to be a literal directly inside the call — `t(ok ? 'a' : 'b')`
runs perfectly and is invisible to the test that checks the scripts against
the dictionary. Where the sentence belongs to a control the server drew, put
it on the control in `data-confirm` instead, translated and filled in there;
`dashboard/users_list.html` does that with an account's address.

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
