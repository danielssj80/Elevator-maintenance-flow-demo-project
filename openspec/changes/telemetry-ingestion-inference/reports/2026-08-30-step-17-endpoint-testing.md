# Step 17 Report — Manual Endpoint Testing

- **Date**: 2026-08-30
- **Change**: telemetry-ingestion-inference
- **Branch**: `feature/telemetry-ingestion-inference`

All requests executed by the agent against the running compose stack. No step
was delegated.

## Stack Preparation

```bash
docker compose build backend inference migrate
docker compose up -d
```

> **`migrate` needs its own build.** `migrate` is a separate compose service
> with `build: ./backend`, so it gets its **own image**
> (`…-migrate`, not `…-backend`). `docker compose build backend inference`
> left it stale, and the stack came up with
> `FAILED: Can't locate revision identified by '3d92a2ed3fb5'` — the migration
> files existed in the source tree and in the backend image, but not in the
> image actually running `alembic upgrade head`. This is the stale-image trap
> from the previous change wearing a different hat; the fix is to include
> `migrate` in any build that touches `alembic/versions/`.

All services healthy after the rebuild.

## Endpoints Tested

### POST /api/telemetry/readings — valid batch

60 readings across 20 elevators.

- Status: **201** ✓
- Response: `accepted: 60`, `rejected_elevator_ids: []`, `batch_id` and
  `trace_id` both present.
- DB: 60 rows, **1 distinct `batch_id`**, **1 distinct `trace_id`**, ambient
  temperatures between 22.04 and 33.84 — stored in Celsius exactly as submitted.

### POST /api/telemetry/readings — partial batch

Three readings, two referencing unknown elevator ids.

- Status: **201** ✓
- Response: `accepted: 1`, `rejected_elevator_ids: ["ELV-ALSO-GONE", "ELV-GONE"]`
- The valid reading was persisted; the batch was not lost to the stale ids.

### POST /api/telemetry/readings — every reading invalid

- Status: **422** ✓
- Response: `No reading in the batch references a known elevator: ELV-NOPE`
- Nothing persisted.

### POST /api/telemetry/readings — 1001 readings

- Status: **422** ✓
- Response: `List should have at most 1000 items after validation, not 1001`

### GET /api/telemetry/readings

- Status: **200** ✓
- Ordered newest first: `13:24:56, 13:14:56, 13:04:56, 12:00:00`
- Celsius preserved (`25.89`); an unconsumed domain signal persisted
  (`vibration_mm_s: 1.78`).
- Unknown elevator id → **200 with `[]`**, not 404 ✓

### POST /api/inference/run — the real thing

```json
{
  "scored": 14,
  "skipped_no_telemetry": 56,
  "out_of_scope": 30,
  "readings_considered": 43,
  "model_version": "8fbb94ff07b7",
  "window_hours": 24,
  "duration_seconds": 0.215178,
  "pruned_readings": 0
}
```

- Status: **200** ✓
- Arithmetic checks out: 100 elevators, 70 in scope, 20 with telemetry of which
  14 in scope → 14 scored and 56 skipped.
- Scores genuinely moved: `ELV-001` 0.7999 → 0.0001, `ELV-003` 0.1105 → 0.9016.
- Spread across the 14 scored: 10 distinct values, min 0.0000, max 0.9016,
  stddev 0.2478.
- Out-of-scope elevators with `last_scored_at IS NOT NULL`: **0** ✓
- Every elevator still holds exactly 6 trend points and 3 features (checked as
  `GROUP BY … HAVING count(*) <> 6` / `<> 3`, both returning 0 rows) ✓
- The explanation was regenerated, and renders the temperature back in Celsius:
  *"High risk: Motor useful life remaining (8% remaining (critical)) is the
  primary driver, combined with Load torque (39.1 Nm …) and Motor temperature
  (40°C …)"* — the full °C → K → model → °C round trip.

### POST /api/inference/run — scorer unreachable

`docker compose stop inference`, then the same call.

- Status: **503** ✓ — not 500
- Response: `{"detail":"Inference service is unavailable"}`
- No traceback and no "Internal Server Error" in the backend log (grep count: 0) ✓
- `last_scored_at IS NOT NULL` still 14, unchanged by the failed run ✓

### Production gating

The **built image**, run with `DEPLOYMENT_ENVIRONMENT=production`:

| Request | Status |
|---|---|
| `POST /api/telemetry/readings` | **404** ✓ |
| `GET /api/telemetry/readings` | **404** ✓ |
| `POST /api/inference/run` | **404** ✓ |
| `GET /api/elevators` | 200 ✓ |
| `GET /api/elevators/ELV-001` | 200 ✓ |
| `GET /health` | 200 ✓ |

The same image with `DEPLOYMENT_ENVIRONMENT=local` reaches both telemetry routes
(422 on an empty body, 200 on the read), confirming the difference is the gate
and not a broken image.

## Distributed Trace

One `POST /api/inference/run` produced a single trace spanning two services:

```
elevator-backend    POST /api/inference/run       (server)
elevator-backend    inference.run                 (domain)
elevator-backend    SELECT x18, UPDATE x14, INSERT x28, DELETE x29
elevator-inference  GET /model
elevator-inference  POST /score
elevator-inference  inference.score               (domain)
```

`service.name` values in Tempo: `elevator-backend`, `elevator-inference`.
n8n becomes the third service in the next change.

Span attributes are counts and identity only:

- `inference.run`: scored 14, skipped_no_telemetry 56, out_of_scope 30,
  readings_considered 43, window_hours 24, pruned_readings 0, model_version.
- `inference.score`: row_count 14, feature_count 7, model_version.

No telemetry value appears on any span, asserted both here and by
`test_the_run_span_carries_no_telemetry_values`.

**Noted, not acted on**: a run issues roughly four statements per scored
elevator (delete + insert for features, delete + insert for trend). At 70
in-scope elevators that is ~280 statements in one transaction. Fine at this
scale and visible in the trace if it ever stops being fine; batching it would
be premature now.

## DB State

Step 17 deliberately mutates the dev database — it runs real inference. Restored
afterwards by truncating `telemetry_readings` and `elevators CASCADE` and
restarting the backend, whose lifespan re-seeds from `predictions.json`.

- Counts back to 100 / 210 / 420 / 0 / 0.
- Risk-score checksum back to `2d3eaded7d948dca394034571e88eb5b`, identical to
  the pre-test baseline.

State restored: **Yes**.

## Outcome

**PASS**
