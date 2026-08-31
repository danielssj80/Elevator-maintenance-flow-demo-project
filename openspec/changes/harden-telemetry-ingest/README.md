# Change: harden-telemetry-ingest

| | |
|---|---|
| **Status** | In progress |
| **Milestone** | M5 — Observability & Orchestration (prerequisite) |
| **Notion tasks** | [Make telemetry ingest idempotent before n8n starts retrying batches](https://app.notion.com/p/3cd3ada00a95817d8340cab9d22e0654) · [Add X-Ingest-Token authentication to the telemetry ingest endpoint](https://app.notion.com/p/3cd3ada00a9581189257dfcffe93a3ad) |
| **Branch** | `feature/harden-telemetry-ingest`, from `main` at `d79845a` |
| **Started** | 2026-08-31 |

## Summary

Gives a telemetry reading an identity — `(elevator_id, recorded_at, source)` —
so that submitting one twice changes nothing, and puts an `X-Ingest-Token` guard
on the two unauthenticated write endpoints. Both are prerequisites for
`n8n-workflow-orchestration` rather than parts of it.

## Why it is a change of its own

The next change puts a retrying scheduler in front of an endpoint that cannot
tell a retry from a new reading, and the inference run averages rows, so a
retried batch weighs double in the window and moves the score silently. Fixing
it inside change 3 would mean one review covering a database migration and a
whole orchestration tier at once, and would mean fixing the data model against a
database that already holds the duplicates. It is smaller, testable on its own —
re-send a batch, assert one set of rows — and it unblocks change 3 cleanly.

The token follows the same logic in the other direction: n8n cannot be
configured to send a credential to an endpoint that does not check one. This
change makes the endpoint check; change 3 makes the producer send.

## Artifacts

- [proposal.md](./proposal.md)
- [design.md](./design.md)
- [tasks.md](./tasks.md)
- [specs/telemetry-ingestion/spec.md](./specs/telemetry-ingestion/spec.md)
