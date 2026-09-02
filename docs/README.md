# Documentation

Eight documents, each answering one kind of question. If you are not sure
where to look, the table below is sorted by what you are trying to do.

| I want to… | Read | Kind |
|---|---|---|
| get it running for the first time | [Getting started](getting-started.md) · [по-русски](getting-started.ru.md) | tutorial |
| operate a deployment | [Operations](operations.md) | how-to |
| run or extend the tests | [Testing](testing.md) | how-to |
| work on the code | [Development](development.md) | how-to |
| look up a setting | [Configuration](configuration.md) | reference |
| understand how it fits together | [Architecture](architecture.md) | explanation |
| know why it was built this way | [Decisions](decisions.md) | explanation |
| know what was considered and not built | [Roadmap](roadmap.md) | explanation |

> [!NOTE]
> The split follows [Diátaxis](https://diataxis.fr/): a tutorial takes you
> by the hand, a how-to solves one problem for someone who already knows the
> subject, a reference is looked up rather than read, and an explanation is
> read rather than followed. Mixing them is what turns a guide into
> something nobody finishes — this set used to be one 1800-line file.

## The short version of each

**[Getting started](getting-started.md)** — eight commands to a service
that answers, then what each of them did; the full stack in Docker below
that, with the output every command should print and the errors you are
most likely to hit.

**[Architecture](architecture.md)** — four layers and the direction
dependencies point; how a link is created, resolved and deleted; the two
cache levels and what invalidates them; how authorization decides.

**[Configuration](configuration.md)** — profiles and precedence, the
settings the deployed profiles refuse to start without, and the ones that
bite. The exhaustive list of the variables an operator sets is
`.env.example`; this page is the rules around it.

**[Operations](operations.md)** — migrations with Alembic, the seven CLI
groups, the maintenance schedule, backups, health checks and upgrades.

**[Testing](testing.md)** — the four levels and what each is for, the two
live runs pytest does not collect, and the five things CI enforces beyond
"the tests passed".

**[Development](development.md)** — the patterns you will meet in the code,
how the frontend decides what to show, and the load profile with the
numbers it produced.

**[Decisions](decisions.md)** — one hundred write-ups in the form *what
was decided, why, and what holds it*. Read this one when the code does
something that looks wrong until you know the reason.

**[Roadmap](roadmap.md)** — work that was considered and never started,
with what each idea would change and what it would cost. Read it before
proposing something, in case the reason it is absent is already written
down.

## Conventions in these documents

| | |
|---|---|
| `>` [!NOTE] blocks | Something easy to miss that changes what you should do |
| `>` [!WARNING] blocks | Something that will cost you data or an outage |
| Collapsed sections | Detail that matters when you hit that case and only then |
| Numbers | Measured on this project, not estimated. Where a number came from a run, the document says which run |
| Code paths | `src/link_shortener/...` — clickable in the GitHub interface |

## Language

The main README exists in [English](../README.md) and
[Russian](../README.ru.md), and so does the tutorial. The deeper guides are
kept in English only: they change with the code, and a translation that
drifts is worse than no translation — it is believed.
