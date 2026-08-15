# Security Policy

Thank you for taking the time to look. A report about this project is
welcome whether it turns out to be a hole, a misunderstanding, or a
question — all three are useful.

## Supported versions

| Version | Supported |
|---|---|
| The latest release | yes |
| Anything older | no |

Fixes go into the next release. Nothing is backported: this is a
single-maintainer project, and promising two supported lines would be
promising something that will not be kept.

## Reporting a vulnerability

**Please do not open a public issue for a security problem.** A public
issue makes the problem known to everyone at the moment it becomes known to
me, and everyone running the code is exposed until there is a fix.

Use GitHub's private reporting instead:

**[Report a vulnerability →](https://github.com/IAMN1/link-shortener/security/advisories/new)**

That is the *Security* tab of this repository, *Report a vulnerability*.
The conversation stays between us until a fix exists, and the report
becomes the draft advisory it is published from.

### What helps most in a report

- What you did, in enough detail to repeat it — a request, a sequence of
  clicks, a curl command.
- What happened, and what you expected instead.
- Which profile and setup you were on: `development`, `staging`,
  `production`, local or Docker. Several behaviours differ between them by
  design, and a few of the sharp edges below exist only in one of them.
- The impact as you see it. A guess is fine; I would rather discuss a wrong
  guess than miss a real one.

## What to expect

| | |
|---|---|
| **First reply** | Within 10 days. It will say whether I could reproduce the problem and what I intend to do |
| **While it is open** | I will tell you what is happening rather than go silent |
| **When it is fixed** | The advisory is published, and you are named as the finder unless you would rather not be |
| **If I go quiet** | If 10 days pass with no reply, the report has fallen through the cracks rather than been dismissed. Nudge me by opening a public issue that says only "sent a security report on <date>, no reply" — with no detail in it |

That last row is there because a project maintained by one person can go
quiet for ordinary human reasons, and a reporter should not have to guess
whether they are being ignored.

## Safe harbour

If you act in good faith under this policy, I will not pursue you, and I
will treat your report as a favour rather than an attack. Concretely:

- Look at the code, run it, break your own copy, poke at a deployment you
  control. That is what the project is for.
- Do not touch data or accounts that are not yours on a deployment you do
  not own.
- Do not run automated scanners against somebody else's instance.
- Give me a chance to fix it before telling everyone.

This project was written as an exercise in doing things properly, and I
learned most of what is in it by taking other people's code apart. If it
helps you do the same, that is the point. Read it, copy it, find what is
wrong with it — and tell me what you found.

## Already known, and not a vulnerability report

These are deliberate, documented, and explained in
[Decisions → Known limits](docs/decisions.md#known-limits). A report about
one of them is not wasted — if you think the reasoning is wrong, say so —
but it is not news:

- **`mask_url` leaves three things unmasked**: credentials in an address
  without `://`, a nested address in percent-encoding, and a token in a
  query string. The third is not maskable in principle — a query parameter
  is not distinguishable from a secret by shape.
- **Unauthenticated deletion reveals whether a code is taken.** A `DELETE`
  on a code that does not exist and on one owned by somebody else answer
  differently. The redirect and the basic info endpoint answer that same
  question publicly anyway.
- **The failover health probe is taken under a lock**, so a slow probe
  blocks callers that would have used the fallback. Bounded by the probe's
  own timeout.
- **`ALL_SERVICES_FAILED` is set and read by nobody.** It is counted, not
  acted on.

Also out of scope, as they are for most projects:

- Anything that needs a machine-in-the-middle position or physical access.
- Denial of service by volume, and load testing of somebody else's
  instance.
- Missing hardening headers, cookie flags or TLS **in the `development`
  profile**. That profile deliberately runs without TLS and with
  non-`Secure` cookies; the deployed profiles do not, and a gap *there* is
  very much a report worth making.
- Scanner output with no working example behind it.
- Email spoofing and content injection with no attack vector shown.

## What I am most interested in

The parts where a mistake would be quiet, in rough order:

- **Authorization.** A path where a caller obtains a permission it does not
  hold — especially privilege escalation through role or permission
  assignment, or anything that lifts an anonymous caller above
  `ANONYMOUS_PERMISSION_CEILING`.
- **Ownership.** Reading or deleting somebody else's link, or seeing the
  owner and traffic of a link you have no claim to.
- **Sessions and tokens.** A refresh token that survives revocation, an
  access token accepted after logout or deactivation, a chain that is not
  revoked when a spent token is replayed.
- **The cache.** Anything that gets a value past the signature, or gets one
  entry to answer for another key.
- **CSRF.** A state-changing request that goes through on a cookie session
  without a valid token.
- **Account enumeration.** Any endpoint that answers differently for a
  registered address than for a free one. Registration is deliberately
  indistinguishable; if some other path gives it away, that is a real
  finding.
