# Step 13 Report — Manual Endpoint Testing

- **Date**: 2026-08-29
- **Change**: 2026-08-28-otel-observability
- **Executed by**: the agent, against the running Docker stack

## Environment

`docker compose up -d` with the observability services. All healthy:
`backend`, `db`, `frontend`, `lgtm`, `otel-collector`.

Telemetry assertions were made by querying Tempo (`:3200`) and Prometheus
(`:9090`) directly, not by reading the code.

## Endpoints Tested

### GET /api/elevators
`200`, 29,104 bytes, 100 elevators, sorted with `ELV-073` (high) first.
Trace shows a server span named for the route template plus three SQLAlchemy
`SELECT` spans (`elevators`, `elevator_trend_points`, `elevator_features`).

### GET /api/elevators/ELV-001
`200`. `trend` has exactly 6 points, `features` exactly 3 — the data-model
invariants hold. Span carries `http.route` = `/api/elevators/{elevator_id}`,
so two different elevators produce one metric series, not two.

### GET /api/elevators/ELV-001/briefing
`200`, `source: fallback`, 333 characters. Fallback is expected: the local
stack has no AWS credentials, and the endpoint deliberately never fails.

Trace contents:

```
GET /api/elevators/{elevator_id}/briefing        http.response.status_code=200
  briefing.generate                              elevator.id=ELV-001
                                                 elevator.risk_level=medium
                                                 briefing.source=fallback
                                                 briefing.cache_hit=false
                                                 gen_ai.provider.name=aws.bedrock
                                                 gen_ai.system=aws.bedrock
                                                 gen_ai.request.model=eu.amazon.nova-lite-v1:0
    chat eu.amazon.nova-lite-v1:0                gen_ai.request.temperature=0.3
                                                 gen_ai.request.max_tokens=450
```

Two things this confirms that unit tests could not:

- The botocore span nests **under** `briefing.generate` in the real runtime,
  so the `anyio.to_thread` offload really does carry the tracing context into
  the worker thread.
- Both provider attribute generations are present on the domain span.

### GET /api/elevators/ELV-999
`404`, body `{"detail":"Elevator not found"}`. The server span records
`http.response.status_code` 404 and its span status is **UNSET**, not
`STATUS_CODE_ERROR` — a missing elevator is an expected outcome, not a fault.

### POST /api/elevators/ELV-001/report
- Invalid body (`{"technician_name": 123}`) → `422` with 3 validation entries.
- Valid body → `201`, `{"status":"ok","message":"Report for ELV-001 received..."}`.
- Unknown elevator → `404`.

### GET /health
`200`. Excluded from tracing on purpose: the container healthcheck fires every
10 seconds and would otherwise dominate the trace store.

## Error Cases

| Case | Expected | Observed |
|---|---|---|
| Unknown elevator, GET | 404 | 404 |
| Unknown elevator, POST report | 404 | 404 |
| Malformed report body | 422 | 422 |
| Bedrock unavailable | 200 with `source: fallback` | 200, `fallback` |

## Prompt-content verification

Searched every attribute of every span in the briefing trace for exact markers:
the system prompt (`"field-service assistant"`), the prompt scaffold
(`"Top prediction drivers"`), a seeded visit-note value (`"Vibration noted"`),
and the first 40 characters of the returned briefing.

**Result: clean.** No prompt, completion or visit-note content on any span.

A first pass using a looser heuristic flagged `db.statement`. That was a false
positive: the SQL text contains the *column name* `last_visit_technician`, and
SQLAlchemy records bound parameters as `$1`-style placeholders rather than
inlining values. Verified before reporting.

## DB State

| Table | Before | After insert | After restore |
|---|---|---|---|
| `visit_reports` | 0 | 1 | 0 |

**Restored**: the created row was deleted by
`DELETE FROM visit_reports WHERE technician_name = 'Manual Test' AND notes = 'step-13 endpoint verification';`
(`DELETE 1`). No other table was mutated.

## E2E (Playwright) — NOT APPLICABLE

This change touches no file under `frontend/`, changes no API response shape and
adds no endpoint. Grafana is a separate audience on its own port and is not
embedded in the React app. Recorded here rather than as an empty E2E report, per
the change's `tasks.md` section 14.

## Outcome

**PASS**
