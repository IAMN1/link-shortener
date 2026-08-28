# What is not built

Ideas this project has met and not taken, kept so that returning to it
after a month does not mean rediscovering them. This is not a plan and
nothing here is promised — each entry says what exists now, what the idea
would change, and what it would cost, so that a later decision is made
against facts rather than against a memory of them.

[All docs](README.md) · [Decisions](decisions.md) ·
[Architecture](architecture.md)

Two neighbours to keep apart. [Decisions](decisions.md) records choices
already made and the measurements behind them; its *Known limits* section
records faults that are understood and deliberately left. This file records
work that was never started. A thing moves from here to *Decisions* the day
it is built, and from here to *Known limits* the day it is refused.

---

## Send the journals somewhere the service does not own

**Now.** `application.log`, `error.log` and `audit.log` are files under
`datas/logs`, rotated by logrotate (`dockers/logrotate.conf`) and read by
whoever can reach the disk. The administrator of the deployment is also the
owner of the journals.

**Why it is worth writing down.** The audit journal exists to reconstruct
an incident, and the people it records are the people who can reach it.
[NIST SP 800-53 AU-9](https://csf.tools/reference/nist-sp-800-53/r5/au/au-9/)
asks that audit information be protected from exactly them; separation of
duties (AC-5) says no one should be able to act and to erase the record of
acting. On one disk that separation cannot be completed, however the
permissions are arranged: an administrator who can write the filesystem can
rewrite the file. Splitting the read permission — which this project does —
makes the bypass *recorded* rather than impossible. Making it impossible
takes a second system.

**What it would take.** A shipper reading the files and forwarding them
(Filebeat, Vector, Fluent Bit — all of them tail a file, which is why
`delaycompress` is already set: the newest archive stays uncompressed long
enough to be finished), and a collector the application cannot write to:
a hosted SIEM, or self-hosted Graylog, Wazuh, or an OpenSearch cluster with
the ingest credentials held elsewhere. Retention then moves there and the
local `rotate` count drops to whatever covers the shipping lag.

**What it would cost.** A second service to run and to keep up, and the
question of what the journals may leave the machine carrying — the audit
line holds destination addresses, and `mask_url` does not clean a token in
a query string (see *Known limits*). Shipping unfiltered means the same
secrets now live in two places instead of one.

**The cheap half, if the full thing is too much.** Ship only `audit.log`,
and only to a collector with append-only credentials. That buys the part
that matters — the record of what was done outliving the person who did
it — without a log pipeline for the traffic journals.

---

## Let the administrator role stop passing every check

**Now.** The `admin` role holds one permission, `admin:all`, and the
authorization service treats it as passing every check — see
`infrastructure/configs/rbac/roles.yaml` and
`rbac_authorization_service.py`.

**Why.** It is the shortest description of an administrator and the reason
no permission can ever be withheld from one. Every control this project
adds around the audit journal is subject to it.

**What it would take.** A named set of permissions that `admin:all` does
not cover, and a decision about who grants them. It does not remove the
bypass — an administrator can still assign themselves the role — so it is
worth doing together with `ROLES_CHANGED`, which is what turns a silent
bypass into a recorded one -- and which now exists: see
[Decisions → The audit journal records what the service does about accounts, and who read it](decisions.md).

---

## The retention arithmetic has an edge

**Now.** `audit.log` is rotated weekly or at 1 GB, whichever comes first,
and 200 generations are kept. At 473 bytes a redirect this covers a year
until traffic passes roughly 14 redirects a second; above that the
generations are consumed faster than the year passes and the oldest
evidence falls off early.

**Why it is here rather than in *Known limits*.** It is not a fault to fix
in place: any pair of numbers has such an edge, and moving it means either
more disk or less history. The honest fix is the first entry in this file —
retention that belongs to a system built for it.

**Nothing warns when it is crossed.** A deployment above that rate keeps
answering and quietly holds less history than the documentation says. A
check would be cheap: compare the age of the oldest generation against the
retention the deployment believes it has, and report it beside the logging
counters in `/api/v1/admin/health`.
