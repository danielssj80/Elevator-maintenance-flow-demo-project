# Step 7 Report — Spec Sync and Format Migration

- Date: 2026-09-13
- Change: harden-tls-renewal

## Before

```
$ openspec validate --specs
✗ spec/production-deployment
Totals: 10 passed, 1 failed (11 items)
```

`production-deployment` had been unvalidatable since it was written: legacy
`S1…S9` prose, no `## Purpose`, no `## Requirements`. The one capability whose
renewal scenario was certified on false evidence was also the one capability the
validator could not read.

## After

```
$ openspec validate --specs
Totals: 11 passed, 0 failed (11 items)
```

Every capability in the repository validates, for the first time.

## What was applied

**`deploy-pipeline`** — one ADDED requirement, *The deploy re-asserts host-level
TLS renewal configuration*, with 4 scenarios.

Appending it at the end of the file put it after `## Files`, `## Constraints` and
`## Out of Scope`, and the validator caught what a human reviewer would not have:

```
✗ Requirement header "..." appears outside the main ## Requirements section.
  Main specs only parse requirements inside that section, so this requirement is
  currently invisible to validate, list, and archive.
```

An invisible requirement is worse than a missing one. Re-inserted at the end of
`## Requirements`, where it parses.

**`production-deployment`** — migrated to the schema format and the renewal
requirement replaced:

| Legacy | Migrated |
|---|---|
| S1 | Requirement: HTTP is redirected to HTTPS |
| S2 | Requirement: The dashboard loads over HTTPS with a trusted certificate |
| S3 | Requirement: The API is reachable over HTTPS (2 scenarios) |
| S4 | Requirement: A post-visit report persists in production |
| S5 | Requirement: The stack restarts automatically after a reboot |
| S6 | Requirement: Shell access is via SSM, with no SSH |
| **S7** | **Requirement: The production certificate renews itself without human intervention** (rewritten, 6 scenarios) |
| — | **Requirement: Certificate expiry is detected from outside the host before it happens** (new, 5 scenarios) |
| S9 | Requirement: The pre-visit briefing works in production via Bedrock |
| S8 | Requirement: CORS is enforced in production |

Order preserved, S9 before S8 as in the original, so the diff reads as a
reformat rather than a rewrite.

## Verification that nothing else changed meaning

Rather than asserting it, every assertion line of the legacy spec was checked for
survival in the migrated one, normalised for markup (54 assertions, S7's
excluded). Nine lines did not match verbatim. Each was examined:

**Eight are `Given` + `When` pairs recombined into a single `WHEN` clause**, which
is what the schema's scenario format expects:

- S5's *"Given the EC2 instance is rebooted"* + *"When the instance completes its
  boot sequence"* → *"WHEN the EC2 instance completes its boot sequence after a
  reboot"*.
- S6's permission precondition folded into *"WHEN an engineer with the
  `AmazonSSMManagedInstanceCore` IAM permission opens an SSM Session Manager
  session"*.
- S8's *"Given the backend is running with `ALLOWED_ORIGINS=…`"* folded into its
  WHEN.
- S9's role, policy and `.env` preconditions folded into its WHEN, and its
  least-privilege list moved from a trailing `**And**` block into the
  requirement's own text — where a constraint on the grant belongs, rather than
  inside one scenario.

**One is a deliberate scope change, declared here rather than left to be found.**
`## Out of Scope` listed *"Monitoring and alerting"*. That is no longer true: this
change adds a scheduled check of the served certificate. The line now reads
*"Alerting beyond a failing GitHub Actions run"*, which is exactly what exists —
a failing workflow run notifies, and nothing more. No paging, no uptime service,
no dashboard.

`## Constraints` also gained one line: *"Renewal configuration is installed from
the repository by the deploy, never edited on the instance"*. `## Files` gained
the five new files.

## Outcome

PASS — 11/11 specs valid, one requirement rewritten, one added, one scope line
corrected, no other meaning changed.
