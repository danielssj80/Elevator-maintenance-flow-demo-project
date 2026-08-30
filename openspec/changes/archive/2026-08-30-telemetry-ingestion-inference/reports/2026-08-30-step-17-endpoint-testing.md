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

---

# Re-run — after adversarial rounds 2 and 3

- **Date**: 2026-08-30 (later the same day)
- **Reason**: rounds 2 and 3 changed observable behaviour — ingest validation,
  per-elevator degradation, the run summary's new field, the fail-closed
  environment default. Round 3 found that this report's boxes were still ticked
  against code that no longer existed. Everything below was re-executed against
  a stack rebuilt from the current tree (`backend`, `migrate`, `inference`).

## What changed since the first run

### Ingest now refuses implausible readings

| Request | Status |
|---|---|
| `ambient_temperature_c: -400` | **422** ✓ |
| `ambient_temperature_c: 300.15` (Kelvin submitted as Celsius) | **422** ✓ |
| `recorded_at: 2099-01-01` | **422** ✓ |
| Valid 60-reading batch | **201**, `accepted: 60` ✓ |

### The run reports the new field

```json
{
  "scored": 14, "skipped_no_telemetry": 56, "skipped_out_of_range": 0,
  "out_of_scope": 30, "readings_considered": 42,
  "model_version": "8fbb94ff07b7", "window_hours": 24,
  "duration_seconds": 0.148029, "pruned_readings": 0
}
```

Same 14/56/30 split as the original run, so the added validation did not change
which elevators are eligible.

### The trend no longer loses a point on the first run after seeding

`ELV-001` before and after the first run of the seeding day:

```
before:  0.6, 0.65, 0.68, 0.75, 0.78, 0.8
after:   0.6, 0.65, 0.68, 0.75, 0.78, 0.0002
```

Index 5 replaced, index 0 preserved. Before the fix this shifted the window and
dropped `0.6`. All 100 seeded elevators now carry `last_scored_at`.

### The production gate holds when nobody configures it

The built image run with **`DEPLOYMENT_ENVIRONMENT` unset entirely** — the state
`docker-compose.prod.yml` actually produces, since it sets the variable nowhere
and loads an out-of-repo env file:

| Request | Status |
|---|---|
| `POST /api/telemetry/readings` | **404** ✓ |
| `POST /api/inference/run` | **404** ✓ |
| `GET /api/elevators` | 200 ✓ |
| `GET /health` | 200 ✓ |

The first run of this report tested the gate by **setting** the variable, which
only ever asks whether the mechanism works when configured. It does. It never
asked whether production configures it — and it did not.

## A false alarm worth recording

The first re-run scored 3 elevators instead of 14 and looked like a regression
from the new ingest validation. It was not: the reusable batch fixture in the
scratchpad had been overwritten with a 10-reading file by the round-3 review
agent, which shares that directory. Regenerating it restored `scored: 14`.
Recorded because "the code regressed" was the wrong first conclusion, and the
cheap check — look at the input before blaming the system — settled it.

## DB State

Restored: counts back to 100 / 210 / 420 / 0, risk-score checksum back to
`2d3eaded7d948dca394034571e88eb5b`.

## Outcome

**PASS**
