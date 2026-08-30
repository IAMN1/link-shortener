<!--
The list below is what CONTRIBUTING.md already asks of a change. It is
here so that both of us can see, before review starts, which parts have
been run and which have not — an honest unticked box costs nothing, while
a ticked one that was not run costs a round trip.
-->

## What this changes

<!-- One or two sentences. The defect, or the thing that could not be done. -->

## Why

<!--
If it fixes something, say how it showed itself — the request, the page,
the command. A refactor with no defect behind it is unlikely to be merged,
so if this is one, say what went wrong that made it necessary.
-->

## How it was checked

<!-- Which check caught it, and how you know it is fixed rather than hidden. -->

---

- [ ] `uv run autopep8 --in-place --recursive src tests` — the one formatter this project runs
- [ ] `uv run pytest tests/` — green, and the coverage floor of 88% held
- [ ] `uv run flake8 src tests`
- [ ] `uv run pylint src` — 9.0 or above
- [ ] `uv run bandit -r src -q`
- [ ] `uv run mypy src` — zero errors
- [ ] There is a test for it, or a sentence below saying why one was not possible
- [ ] Every commit carries `Signed-off-by` (`git commit -s`) — the DCO, in place of a CLA

If it touches HTTP or the frontend:

- [ ] `uv run python tests/live/smoke_test.py`
- [ ] `uv run python tests/live/browser_test.py` — needs `--group browser`

If it touches a string a visitor reads:

- [ ] `pybabel extract` / `update` / `compile` run, and no `msgid`, no `msgstr` and no fuzzy entry changed by accident

If it adds a setting or an endpoint:

- [ ] A new setting has its line in `.env.example` — a test fails if it does not
- [ ] A new endpoint has its entry in `web/schemas/openapi.py` — likewise
- [ ] A number written into a document was measured on this tree, not recalled

<!--
Anything unticked is fine. Say which and why, here:
-->
