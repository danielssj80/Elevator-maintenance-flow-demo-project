# Proposal: harden-telemetry-ingest

## Why

`telemetry-ingestion-inference` shipped an ingest endpoint with no notion of a
repeated submission, and the next change puts a retrying scheduler in front of
it. Two facts, both verified in the merged code:

- **A reading has no identity.** `telemetry_readings` carries no uniqueness
  constraint of any kind (`app/models/telemetry.py`), and `batch_id` is minted
  server-side per request (`app/services/telemetry_service.py:70`). Submitting
  the same payload twice therefore produces two independent sets of rows that
  nothing can tell apart afterwards.
- **The inference run averages rows, not readings.**
  `TelemetryRepository.aggregate_window` builds each elevator's feature vector
  with `func.avg(...)` over whatever rows fall in the window
  (`app/repositories/telemetry_repository.py:88-96`). A batch present twice is
  weighted twice, which drags the aggregate toward that batch and moves the
  resulting risk score. There is no error, no log line, and the only visible
  symptom is a score that is subtly wrong.

This is latent only because nothing retries yet. `n8n-workflow-orchestration`
ends that: the ingest workflow runs on a schedule and **n8n retries a failed
node by re-sending the same payload**, so a single transient 500 or timeout
between n8n and the backend is enough to double-weight a tick. Fixing it
afterwards means fixing it against a database that already contains the
duplicates.

The same endpoint is also unauthenticated. Production is protected by absence —
the routers are not registered when `deployment_environment` is production — but
that gate says nothing about who may write in any environment where the routers
*are* registered, and the next change introduces exactly such a producer. The
token has to exist before n8n can be configured to send one.

## What Changes

- Give a reading an identity: a unique constraint on
  `(elevator_id, recorded_at, source)`, and an ingest path that inserts with
  `ON CONFLICT DO NOTHING` and reports what it skipped.
- Deduplicate within a batch as well as across requests, so a producer that
  repeats a reading inside one payload gets the same guarantee as one that
  repeats the payload.
- Report the outcome honestly: `accepted` becomes the number of rows actually
  inserted, and a new `duplicates_ignored` field carries the rest.
- Drop `ix_telemetry_readings_elevator_recorded`, which the new unique index
  subsumes — its columns are a prefix of the unique index and PostgreSQL scans a
  btree backwards for the `DESC` ordering.
- Require an `X-Ingest-Token` header, compared with `secrets.compare_digest`, on
  the two unauthenticated write endpoints — `POST /api/telemetry/readings` and
  `POST /api/inference/run` — with an unset token meaning open, and a startup
  warning when that is the case.
- Configure a token in `docker-compose.yml`, and assert that it is configured
  there. A guard proven only in a fixture is the exact defect round 3 of the
  previous change found in the production gate.

### Why `POST /api/inference/run` is included

The Notion task names the ingest endpoint. Both endpoints are the same
unauthenticated write surface, the next change makes n8n call both, and locking
one while leaving the other open would be a gap with no rationale behind it. The
cost is one shared dependency rather than two.

## Capabilities

### Modified Capabilities

- `telemetry-ingestion`: gains an identity for a reading and the guarantee that
  repeated submission is a no-op, and gains a shared-secret guard on its write
  endpoint. The read endpoint, the unit rules, the unknown-elevator tolerance
  and the production gate are unchanged.

### New Capabilities

- None.

## Impact

- **New files**: `backend/app/core/ingest_auth.py`,
  `backend/alembic/versions/<rev>_telemetry_readings_unique_identity.py`,
  `backend/tests/unit/test_ingest_auth.py`,
  `backend/tests/integration/test_telemetry_idempotency.py`.
- **Modified files**: `backend/app/models/telemetry.py`,
  `backend/app/repositories/telemetry_repository.py`,
  `backend/app/schemas/telemetry.py`,
  `backend/app/services/telemetry_service.py`,
  `backend/app/routers/telemetry.py`, `backend/app/routers/inference.py`,
  `backend/app/main.py`, `backend/app/core/config.py`, `docker-compose.yml`,
  `docs/api-spec.yml`, `docs/data-model.md`, and the existing telemetry tests.
- **Not modified**: `docker-compose.prod.yml`. The routers are still not
  registered in production, so nothing there changes.
- **Frontend**: none. No response the dashboard reads is touched. The mandatory
  Playwright step is N/A.
- **Database**: one unique index added, one redundant index dropped, and a
  one-off deletion of pre-existing duplicates so the constraint can be created.
  The deletion keeps the lowest `id` per identity and is a no-op on an empty
  table — which is what production has, the routers having never been
  registered there.
- **API contract**: `TelemetryIngestResponseSchema` gains `duplicates_ignored`
  and `accepted` changes meaning from "readings referencing a known elevator" to
  "rows inserted". Additive for any consumer reading `batch_id`; the only
  current consumer is `curl`.
- **Deferred to `n8n-workflow-orchestration`**: configuring the credential
  inside n8n and sending the header from the ingest workflow. This change makes
  the endpoint check a token; the next change makes the producer send one.
