# Design: harden-telemetry-ingest

## Layering

Nothing here moves between layers. The identity constraint is declared on the
model and enforced by the database; the conflict-tolerant insert is a
`repositories/` concern; deciding what counts as accepted and what counts as a
duplicate is a `services/` concern; the token check is a router-level
dependency in `core/`. Routers stay a boundary that parses, delegates and
returns.

## Decision 1 — a natural key, not a client-supplied idempotency key

The identity of a reading is `(elevator_id, recorded_at, source)`.

The alternative considered was an HTTP-style idempotency key: the producer mints
a key per batch, the server records it, and a repeat returns the original
response. It is the more general answer and it was rejected for this system:

- It only works if the producer preserves the key across a retry. Making
  correctness depend on the orchestrator's configuration is exactly the
  dependency this change exists to remove.
- It needs a second table and an expiry policy for it.
- It protects a *batch*, not a *reading*. Two overlapping batches with different
  keys — a catch-up batch after an outage re-sending the last tick, which the
  1000-row bound explicitly anticipates — still double-weight the overlap.

The natural key protects the thing the inference run actually averages, and it
holds no matter which layer retried or whether the producer knew it did.

**Why `source` is in the key.** Two producers reporting the same elevator at the
same instant are two independent observations, and averaging both is correct.
Leaving `source` out would silently discard the second one. A retry never
changes `source`, so including it costs the guarantee nothing.

**What the key does not cover.** If n8n retries the *whole workflow execution*
rather than the failed node, the Code node runs again and stamps fresh
`recorded_at` values. Those rows are a genuinely new sample of the sensors, not
a duplicate, and they are supposed to be stored. Node-level retry — the default,
and the case in the Notion task — re-sends the identical payload and is fully
covered.

## Decision 2 — `ON CONFLICT DO NOTHING`, and nothing else

The insert becomes
`pg_insert(TelemetryReading).values([...]).on_conflict_do_nothing(index_elements=[...]).returning(TelemetryReading.id)`,
and the count of returned ids is what `accepted` reports.

Read-then-insert was rejected outright: two simultaneous retries both read
"absent" and both insert, which is precisely the race a scheduler produces.

**An in-service pre-deduplication was written and then removed.** The plan was
to drop repeats within the batch in Python first, so that the intra-batch rule
was stated explicitly rather than resting on PostgreSQL's speculative-insertion
semantics. It was deleted because it survived its own mutation: with the pass
removed, every test stayed green, because the single multi-row `INSERT`
already skips a row conflicting with one inserted earlier in the same statement.
Ten lines that look like a guard and enforce nothing are exactly the defect this
project has paid for repeatedly, so the reliance is documented in
`create_many`'s docstring and pinned by a test instead of being restated in code
that does not run.

## Decision 3 — the response tells the truth about what happened

`accepted` changes meaning from "readings referencing a known elevator" to
"rows inserted", and `duplicates_ignored` carries the difference.
`rejected_elevator_ids` is untouched. A full retry therefore answers
`accepted: 0, duplicates_ignored: 100`, which is what a scheduler should log.

The returned `batch_id` labels the rows this request inserted, so on a full
retry it labels none. Returning the *original* batch id instead was considered
and rejected: it needs a lookup on the hot path to answer a question nobody
asks, and it would report a provenance the current request did not create. The
spec states the retry case explicitly so the zero-row `batch_id` is a documented
outcome rather than a surprise.

## Decision 4 — the migration deletes before it constrains

Creating the unique index on a table that already holds duplicates fails. The
migration deletes duplicates first, keeping the lowest `id` per identity:

```sql
DELETE FROM telemetry_readings a
USING telemetry_readings b
WHERE a.elevator_id = b.elevator_id
  AND a.recorded_at = b.recorded_at
  AND a.source      = b.source
  AND a.id > b.id;
```

On an empty table this is a no-op, which is what production has: the routers
have never been registered there, so nothing has ever written to it. The
downgrade drops the unique index and restores the old one; it cannot restore
deleted rows, and says so in its docstring.

`recorded_at` is `timestamptz`, so equality compares absolute instants and two
producers expressing the same moment in different offsets collide correctly.

**Index bookkeeping.** `ix_telemetry_readings_elevator_recorded` covers
`(elevator_id, recorded_at DESC)`. The new unique index covers
`(elevator_id, recorded_at, source)` — the same leading columns, so it covers
the same predicate and the planner supplies the ordering itself.

**Which query actually wants it.** Only `TelemetryRepository.list_for_elevator`,
the read endpoint. The inference run's `aggregate_window` filters on
`recorded_at` alone and groups by `elevator_id`, so it is served by
`ix_telemetry_readings_recorded` and is unaffected either way. An earlier draft
of this section, and the comment it came from, credited the index to "the window
query the inference run issues once per elevator" — a query that does not exist.

Measured rather than assumed, on a 200,000-row table: the read query costs
**5 buffers / 0.31 ms** against the unique index alone, and **4 buffers /
0.21 ms** with the old index also present. The exact plan node is data-dependent
— both `Index Scan Backward` and a bitmap scan plus a small sort have been
observed on different row distributions — so the figure that carries the
decision is the difference between those two, not the shape of either. It does
not justify a second index write on every insert into the hottest table in the
schema, so the old index is dropped in the same migration and recreated on
downgrade. `ix_telemetry_readings_recorded`, which the prune and the staleness
gauge use and which does not lead with `elevator_id`, stays.

## Decision 5 — the token guard, and where it is proven

A `require_ingest_token` dependency in `app/core/ingest_auth.py`, applied to the
two write routes. `secrets.compare_digest` against
`settings.telemetry_ingest_token`; absent and wrong both produce the same 401
body, so the response cannot be used to probe whether a token is configured.

`telemetry_ingest_token` defaults to `None`, meaning open. That default is a
deliberate liability and is handled by putting the guard where it can be
checked rather than by hoping:

- `docker-compose.yml` sets `TELEMETRY_INGEST_TOKEN` for the `backend` service,
  and a test parses that file and asserts it. Round 3 of the previous change
  found the production gate unenforced in the deployed configuration while
  passing every test that set the variable by hand; a test that reads the
  compose file is the only kind that would have caught it.
- `build_app` logs a warning when it registers these routers with no token
  configured, so a misconfigured environment announces itself at startup.

Fail-open is right here and fail-closed was right for the production gate,
because the two guard different things. The production gate protects an
internet-facing deployment where forgetting to configure is the likely mistake.
This token sits on routers that only exist outside production; making it
fail-closed would break `pytest` and a bare `uvicorn` run for every contributor,
and the endpoint it protects is already unreachable in the environment where
being wrong is dangerous.

The dev token is a fixed non-secret literal in `docker-compose.yml`. It is a
local development credential for a demo stack, not a secret, and inventing a
generated one would create a key-distribution problem for n8n in the next change
with nothing gained.

## Out of scope

- Configuring the credential inside n8n and sending the header from the ingest
  workflow. That belongs to `n8n-workflow-orchestration`, which is the change
  that introduces the producer.
- Any authentication on the read endpoints or on the pre-existing public API.
  This change guards writes; the fleet API's lack of authentication is a
  separate, larger question.
- Rotating or storing the token anywhere other than the environment.
- Retention, partitioning or BRIN indexes on `telemetry_readings`. Unchanged and
  still deferred above ~50 M rows.
