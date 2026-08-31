# Step 10 Report — Manual Endpoint Testing

- **Date**: 2026-08-31
- **Change**: harden-telemetry-ingest
- **Branch**: `feature/harden-telemetry-ingest`

Executed by the agent against the running compose stack, not against the test
suite. Token used: `local-dev-ingest-token`, the value `docker-compose.yml` sets.

## The stale-image trap, one layer deeper than documented

`docker compose build backend` was not enough. The first run showed the
constraint absent and `ix_telemetry_readings_elevator_recorded` still present:
the migration is applied by the **`migrate`** service, which builds its own image
from the same Dockerfile. Rebuilding `backend` leaves `migrate` on the old
image, and it exits successfully having found nothing to do — no error, no
warning, just an unmigrated database.

```bash
docker compose build backend migrate
docker compose up -d --force-recreate migrate
docker compose up -d db backend inference
```

After that:

```
$ psql -c "SELECT conname FROM pg_constraint WHERE conrelid='telemetry_readings'::regclass AND contype='u';"
uq_telemetry_readings_identity

$ psql -c "SELECT indexname FROM pg_indexes WHERE tablename='telemetry_readings' ORDER BY 1;"
ix_telemetry_readings_recorded
telemetry_readings_pkey
uq_telemetry_readings_identity
```

The old composite index is gone and the unique one is in place, in the database
the application actually talks to.

## Configuration reaching the process

```
$ docker compose exec -T backend printenv TELEMETRY_INGEST_TOKEN DEPLOYMENT_ENVIRONMENT
local-dev-ingest-token
local
```

And the startup warning is correctly **absent** from the backend log, because a
token is configured. That is the positive control for
`test_registering_the_routers_unguarded_logs_a_warning`.

## Endpoints Tested

### POST /api/telemetry/readings — the token

| Case | Expected | Observed |
|---|---|---|
| No `X-Ingest-Token` | 401 | **401** |
| Wrong token | 401 | **401** |
| Bodies of the two above | identical | identical: `{"detail":"Invalid or missing X-Ingest-Token"}` |
| Correct token | 201 | **201**, `accepted: 2` |

### POST /api/telemetry/readings — idempotency

| Case | Expected | Observed |
|---|---|---|
| First send, 2 readings | `accepted 2, duplicates 0` | **`accepted 2, duplicates 0`** |
| Identical resend | `accepted 0, duplicates 2` | **`accepted 0, duplicates 2`** |
| Row count after the resend | unchanged at 2 | **2** |
| Partial overlap: 2 stored + 1 new | `accepted 1, duplicates 2` | **`accepted 1, duplicates 2`** |
| Same elevator and instant, `source` changed | both stored | **`accepted 2`** |
| A retry returns a new `batch_id` | yes, labelling no rows | confirmed |

> The partial-overlap case was run twice. The first attempt recomputed
> `recorded_at` from `date -u -d '-5 minutes'`, which produced a *later* instant
> than the stored readings, so nothing overlapped and it reported
> `accepted 3, duplicates 0`. That was the test data being wrong, not the
> endpoint. Rerun reusing the stored timestamp, it reported `accepted 1,
> duplicates 2`. Recorded because a run like the first one, read carelessly,
> looks like the feature not working.

### POST /api/inference/run

| Case | Expected | Observed |
|---|---|---|
| No `X-Ingest-Token` | 401 | **401** |
| Wrong token | 401 | **401** |
| Correct token | 200, run completes | **200** — `scored 2, readings_considered 8, skipped_no_telemetry 68, out_of_scope 30` |

### The end-to-end guarantee

The point of the whole change, exercised against the live stack:

1. Ingest four batches (8 distinct readings across ELV-001 and ELV-002).
2. Run inference. Record `risk_score` for both elevators.
3. **Re-POST every one of the four batches** — the retry. Each answered
   `accepted 0`, and the row count stayed at 8.
4. Run inference again.

```
scores after run 1:  ELV-001|0.0002   ELV-002|0
scores after run 2:  ELV-001|0.0002   ELV-002|0
MATCH: a retried batch did not move the score
```

Trend length stayed at exactly 6 points for both, so the second run overwrote
today's point rather than shifting the window — the cadence rule still holds
with the new insert path.

(The scores are far below the seeded 0.7999 for ELV-001 because the synthetic
readings used here — 27 °C, 1500 rpm, 40 Nm, 12 000 h — describe a healthy unit.
That is the model working, not a regression.)

## Error Cases

- 401 on both write endpoints, absent and wrong indistinguishable ✓
- Unknown elevator ids still filtered and reported rather than failing the batch ✓ (unchanged behaviour, re-confirmed)
- No 500 observed on any request ✓

## E2E Playwright (step 11)

**N/A.** No frontend file is touched by this change and no response the dashboard
reads changes shape: `GET /api/elevators` and `GET /api/elevators/{id}` are
untouched. The only altered response body is `POST /api/telemetry/readings`,
which the frontend never calls.

## DB State

Snapshotted into `bk_elevators` / `bk_features` / `bk_trend` before the
inference runs, and restored afterwards inside one transaction: `risk_score`,
`risk_level`, `nl_explanation` and `last_scored_at` written back from the
snapshot, `elevator_features` and `elevator_trend_points` deleted and
reinserted, both id sequences `setval`'d, and the 8 telemetry rows deleted by
`source LIKE 'manual-step-10%'`.

> The restore silently did nothing on the first attempt: `docker exec` without
> `-i` does not forward stdin, so `psql` received an empty script and exited 0.
> The giveaway was `last_scored_at` still holding the run's timestamp. Rerun with
> `docker exec -i`, it reported `UPDATE 100 / DELETE 210 / INSERT 210 / DELETE
> 420 / INSERT 420 / DELETE 8`.

| Table | Pre-test | Post-test |
|---|---|---|
| `elevators` | 100 | 100 |
| `elevator_features` | 210 | 210 |
| `elevator_trend_points` | 420 | 420 |
| `telemetry_readings` | 0 | 0 |
| `visit_reports` | 0 | 0 |

Spot check after restore: `ELV-001 | 0.7999 | medium`, `last_scored_at
2026-08-30 17:56:44+00` — the pre-existing values, not the run's.

**State restored: Yes.**

## Outcome

**PASS**
