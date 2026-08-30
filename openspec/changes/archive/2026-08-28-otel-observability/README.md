# Change: otel-observability

| | |
|---|---|
| **Status** | Archived — 2026-08-29 |
| **Milestone** | M5 — Observability & Orchestration |
| **Notion task** | [OpenTelemetry instrumentation and Grafana observability stack](https://app.notion.com/p/3ca3ada00a9581219edbccdb65a6b5a7) |
| **Branch** | `feature/2026-08-28-otel-observability` |
| **Started** | 2026-08-28 |

## Summary

Instruments the backend with the OpenTelemetry SDK, adds an OTel Collector that fans telemetry out to a local Grafana/Prometheus/Tempo stack and to Grafana Cloud, and exposes a small set of derived fleet-health metrics. First of the three changes in milestone M5.

## Artifacts

- [proposal.md](./proposal.md)
- [design.md](./design.md)
- [tasks.md](./tasks.md)
- [specs/observability/spec.md](./specs/observability/spec.md)

## Reviews

Three adversarial passes, two of them by independent sessions with no prior
context. Reports in `reports/`:

| Round | Reviewer | Verdict | Found |
|---|---|---|---|
| 1 | the implementing agent | PASS WITH GAPS | 1 Major (dead logs pipeline) |
| 2 | independent session, 7 mutations | FAIL | 1 Blocker, 6 Majors |
| 3 | independent session, 21 mutations | FAIL | 2 Blockers, 4 Majors — four of them regressions from round 2 |

The recurring lesson: mutation testing found what reading the diff did not, and
every unreviewed batch of fixes introduced fresh defects of the class it was
fixing.

## Related

- Architecture reference: [M5 — Observability & Orchestration](https://app.notion.com/p/3ca3ada00a9581379a39c6657f201179)
- Followed by `telemetry-ingestion-inference` and `n8n-workflow-orchestration`
