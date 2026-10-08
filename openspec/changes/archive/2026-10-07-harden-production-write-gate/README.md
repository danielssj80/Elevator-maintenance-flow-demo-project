# Change: harden-production-write-gate

| | |
|---|---|
| **Status** | Archived — 2026-10-07 |
| **Milestone** | M5 — Observability & Orchestration (change 1 of 2 for *Run the n8n orchestration tier in production*) |
| **Notion task** | [Run the n8n orchestration tier in production](https://app.notion.com/p/3f23ada00a9581debafae833faa5f248) · absorbs [Harden the production gate](https://app.notion.com/p/3cd3ada00a9581f3bd77de5c6838ae78) |
| **Branch** | `feature/harden-production-write-gate`, from `main` (`2c45d7f`) |
| **Reviews** | Independent cold-start session, 2026-10-07: **PASS WITH GAPS**, 0 blockers, 0 majors, 5 minors + 3 nits — all addressed, see `reports/2026-10-07-step-12-adversarial-review.md` |
| **Started** | 2026-10-07 |

## Summary

Makes it safe for production to register the telemetry and inference routers
before anything calls them: allow-list environment classification, registration
only with a configured token of at least 32 characters, a fail-closed guard in
production, the read endpoint behind the same token, and nginx rate limiting.
Production behaviour is unchanged at merge — no token is provisioned there until
change 2 (`serverless-n8n-orchestration`).
