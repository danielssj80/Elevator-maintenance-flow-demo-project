# Change: telemetry-ingestion-inference

| | |
|---|---|
| **Status** | Archived — 2026-08-30 |
| **Milestone** | M5 — Observability & Orchestration |
| **Notion task** | [Telemetry ingestion and daily risk inference](https://app.notion.com/p/3ca3ada00a9581edaf8efb81852aef9d) |
| **Branch** | `feature/telemetry-ingestion-inference` (stacked on `feature/2026-08-28-otel-observability`) |
| **Started** | 2026-08-30 |

## Summary

Adds the `telemetry_readings` table and its ingest endpoint, and replaces the offline-only scoring path with a real inference job: a dedicated stateless `inference` service that owns the XGBoost model, and a backend service that aggregates a telemetry window, re-scores the in-scope fleet and shifts the 6-day trend. Second of the three changes in milestone M5.

## Why the branch is stacked

`backend/app/core/telemetry.py` and the OTel `Settings` attributes exist only on
`feature/2026-08-28-otel-observability`, which is not yet merged to `main`. This
change consumes them (ingest spans, `trace_id` provenance, the
`n8n → backend → inference → postgres` trace), so it branches from there rather
than from `main`. Merge order is otel first, then this.

## Reviews

Four adversarial passes, three of them by independent sessions with no prior
context. Reports in `reports/`:

| Round | Reviewer | Verdict | Found |
|---|---|---|---|
| 1 | the implementing agent | FAIL | 3 Majors |
| 2 | independent session | FAIL | 4 Majors, incl. round 1's own fix shipped untested |
| 3 | independent session | FAIL | 2 Blockers, 5 Majors — the production gate was unenforced in the deployed configuration |
| 4 | independent session | FAIL | 3 Majors, no Blockers — incl. round 3's fix having no regression guard |

All findings addressed and mutation-checked. The recurring defect across every
round was the same: a guard that exists and is tested beside the code path that
actually runs, rather than on it. Five instances, each found by deleting the
guard and watching the suite stay green — never by reading the test.

## Artifacts

- [proposal.md](./proposal.md)
- [design.md](./design.md)
- [tasks.md](./tasks.md)
- [specs/telemetry-ingestion/spec.md](./specs/telemetry-ingestion/spec.md)
- [specs/risk-inference/spec.md](./specs/risk-inference/spec.md)
